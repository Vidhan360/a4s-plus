'use client';

import { HelpCircle, Sparkles } from 'lucide-react';
import * as React from 'react';

import { FactorBarChart } from '@/components/charts/factor-bar-chart';
import { RiskBadge } from '@/components/domain/risk-badge';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { formatNumber } from '@/lib/format';
import type { RiskFactor, TwinRiskState } from '@/lib/types';

const BAND_COLORS = ['hsl(152 68% 45%)', 'hsl(42 96% 56%)', 'hsl(25 95% 57%)', 'hsl(0 84% 60%)'];

function severityColor(severity: number): string {
  if (severity >= 0.75) return BAND_COLORS[3];
  if (severity >= 0.5) return BAND_COLORS[2];
  if (severity >= 0.25) return BAND_COLORS[1];
  return BAND_COLORS[0];
}

/**
 * "WHY THIS RISK?" panel.
 *
 * The rule engine's contributions are *exact*: each one is `weight × severity`
 * and they sum to the reported score, so the panel is allowed to present them
 * as a definitive decomposition rather than an approximation.
 */
export function WhyThisRisk({ risk }: { risk: TwinRiskState }) {
  const factors = risk.all_factors.filter((factor) => factor.contribution > 0);
  const totalContribution = factors.reduce((sum, factor) => sum + factor.contribution, 0);

  return (
    <Card data-testid="why-this-risk">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="size-3.5 text-primary" />
            Why this risk?
          </CardTitle>
          <div className="flex items-center gap-2">
            <RiskBadge category={risk.category} score={risk.score} />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="cursor-help">
                  <HelpCircle className="size-3.5 text-muted-foreground" />
                </span>
              </TooltipTrigger>
              <TooltipContent>
                Every contribution below is the configured weight multiplied by the measured
                severity of that vital. They sum exactly to the weighted severity that produces the
                0–100 score, so nothing is approximated or sampled.
              </TooltipContent>
            </Tooltip>
          </div>
        </div>
        <CardDescription>
          Transparent decomposition of the rule-engine score. Raw weighted severity{' '}
          {formatNumber(risk.raw_ratio, 3)} is mapped onto 0–100 using a calibration ratio of{' '}
          {formatNumber(risk.scale_ratio, 2)}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {factors.length === 0 ? (
          <p className="rounded-lg border border-dashed border-white/[0.09] px-4 py-6 text-center text-xs text-muted-foreground">
            No vital is outside its reference band, so nothing is contributing to the score.
          </p>
        ) : (
          <>
            <FactorBarChart
              data={factors.map((factor) => ({
                feature: factor.feature,
                value: factor.contribution,
              }))}
              colorFor={(entry) => {
                const match = factors.find((factor) => factor.feature === entry.feature);
                return severityColor(match?.severity ?? 0);
              }}
              height={Math.max(160, factors.length * 30)}
            />

            <ul className="space-y-2.5">
              {factors.map((factor) => (
                <FactorRow
                  key={factor.feature}
                  factor={factor}
                  share={totalContribution > 0 ? factor.contribution / totalContribution : 0}
                />
              ))}
            </ul>
          </>
        )}

        <div className="rounded-lg border border-primary/25 bg-primary/[0.07] px-4 py-3">
          <p className="label-muted text-primary">Recommended action</p>
          <p className="mt-1 text-xs leading-relaxed">{risk.recommended_action}</p>
        </div>

        {Object.keys(risk.trends).length > 0 ? (
          <div className="space-y-2">
            <p className="label-muted">Short-window trends</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(risk.trends).map(([key, value]) => (
                <Badge key={key} variant="outline" className="font-mono">
                  {key} {value > 0 ? '+' : ''}
                  {formatNumber(value, 2)}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function FactorRow({ factor, share }: { factor: RiskFactor; share: number }) {
  return (
    <li className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-xs font-medium">{factor.label}</p>
        <p className="font-mono text-[0.68rem] tabular-nums text-muted-foreground">
          value {factor.value === null ? '—' : formatNumber(factor.value, 1)} · severity{' '}
          {formatNumber(factor.severity, 2)} × weight {formatNumber(factor.weight, 1)} ={' '}
          <span className="text-foreground">{formatNumber(factor.contribution, 2)}</span>
        </p>
      </div>
      <Progress
        value={Math.min(100, share * 100)}
        className="mt-2"
        indicatorClassName="bg-gradient-to-r from-primary to-accent"
      />
      <p className="mt-1.5 text-[0.68rem] leading-relaxed text-muted-foreground">{factor.detail}</p>
    </li>
  );
}
