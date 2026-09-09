'use client';

import { useMutation, useQuery } from '@tanstack/react-query';
import { BrainCircuit, Play, TrendingUp } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { FactorBarChart } from '@/components/charts/factor-bar-chart';
import { ProbabilityChart } from '@/components/charts/probability-chart';
import { RiskBadge } from '@/components/domain/risk-badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { errorMessage } from '@/lib/api-error';
import { DISCLAIMERS, PERM } from '@/lib/constants';
import { formatNumber, formatPercent } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { ContributionsPayload, ModelDescription } from '@/lib/types';

interface RunResult {
  personnel_id: string;
  model_name: string;
  model_version: string;
  horizon_minutes: number;
  predicted_category: string;
  risk_probability: number;
  explanation: ContributionsPayload;
  recommended_action: string;
  inference_ms: number;
  data_provenance: string;
  readings_used: number;
  persisted_id?: string | null;
  disclaimer?: string;
}

interface CompareResult {
  personnel_id: string;
  call_sign: string;
  readings_used: number;
  results: {
    model_name: string;
    model_version?: string;
    available: boolean;
    predicted_category?: string;
    risk_probability?: number;
    inference_ms?: number;
    explanation_method?: string;
    unavailable_reason?: string | null;
    error?: string;
  }[];
  note: string;
}

/**
 * Prediction + explainability panel.
 *
 * The explanation method is whatever the backend actually used — occlusion
 * sensitivity for the LSTM, exact weights for the rule baseline, impurity or
 * permutation importance for gradient boosting. The panel prints that method
 * verbatim rather than labelling everything "SHAP", which would be false.
 */
export function PredictionPanel({ personnelId }: { personnelId: string }) {
  const { can } = useSession();
  const [model, setModel] = React.useState<string>('__default__');
  const [result, setResult] = React.useState<RunResult | null>(null);

  const models = useQuery({
    queryKey: qk.models,
    queryFn: () => api.get<ModelDescription[]>('/predictions/models'),
    enabled: can(PERM.predictionRead),
    staleTime: 5 * 60_000,
  });

  const run = useMutation({
    mutationFn: () =>
      api.post<RunResult>(
        `/predictions/${personnelId}/run`,
        {},
        model === '__default__' ? { persist: true } : { model, persist: true },
      ),
    onSuccess: (data) => {
      setResult(data);
      toast.success(`Forecast: ${data.predicted_category}`, {
        description: `${data.model_name} ${data.model_version} · ${formatNumber(data.inference_ms, 1)} ms`,
      });
    },
    onError: (error) => toast.error('Prediction failed', { description: errorMessage(error) }),
  });

  const compare = useQuery({
    queryKey: ['predictions', personnelId, 'compare'],
    queryFn: () => api.get<CompareResult>(`/predictions/${personnelId}/compare`),
    enabled: false,
  });

  if (!can(PERM.predictionRead)) return null;

  const explanation = result?.explanation;

  return (
    <Card data-testid="prediction-panel">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <BrainCircuit className="size-3.5 text-primary" />
            30-minute forecast
          </CardTitle>
          <div className="flex items-center gap-2">
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger className="h-8 w-[190px] text-xs" aria-label="Prediction model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default__">Configured default</SelectItem>
                {(models.data ?? []).map((entry) => (
                  <SelectItem key={entry.name} value={entry.name} disabled={!entry.available}>
                    {entry.name}
                    {entry.available ? '' : ' (unavailable)'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {can(PERM.predictionRun) ? (
              <Button size="sm" loading={run.isPending} onClick={() => run.mutate()} data-testid="run-prediction">
                <Play />
                Run
              </Button>
            ) : null}
          </div>
        </div>
        <CardDescription>
          Forecasts the rule engine&apos;s risk category 30 simulated minutes ahead from the recent
          telemetry window. {DISCLAIMERS.ml}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {run.isPending ? <LoadingPanel rows={4} /> : null}
        {run.isError ? <ErrorPanel error={run.error} onRetry={() => run.mutate()} /> : null}

        {!result && !run.isPending && !run.isError ? (
          <EmptyState
            title="No forecast requested yet"
            description="Run the model to produce a forecast and its explanation for this soldier's latest telemetry window."
            icon={TrendingUp}
            className="border-0"
          />
        ) : null}

        {result ? (
          <>
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <RiskBadge category={result.predicted_category} pulse />
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    P(elevated) {formatPercent(result.risk_probability, 1)}
                  </span>
                </div>
                <dl className="space-y-1.5">
                  {[
                    { label: 'Model', value: `${result.model_name} ${result.model_version}` },
                    { label: 'Horizon', value: `${result.horizon_minutes} simulated minutes` },
                    { label: 'Window', value: `${result.readings_used} readings` },
                    { label: 'Inference', value: `${formatNumber(result.inference_ms, 2)} ms` },
                    { label: 'Input provenance', value: result.data_provenance },
                  ].map((entry) => (
                    <div key={entry.label} className="flex items-baseline justify-between gap-3">
                      <dt className="label-muted">{entry.label}</dt>
                      <dd className="font-mono text-[0.7rem] tabular-nums">{entry.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
              <div>
                <p className="label-muted mb-1">Class probabilities</p>
                <ProbabilityChart probabilities={explanation?.class_probabilities ?? {}} />
              </div>
            </div>

            <div className="rounded-lg border border-primary/25 bg-primary/[0.07] px-4 py-3">
              <p className="label-muted text-primary">Recommended action</p>
              <p className="mt-1 text-xs leading-relaxed">{result.recommended_action}</p>
            </div>

            {explanation ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="label-muted">Explanation</p>
                  <Badge variant="secondary">{explanation.method}</Badge>
                </div>
                <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                  {explanation.method_description}
                </p>
                {explanation.narrative ? (
                  <p className="text-xs leading-relaxed text-foreground/90">
                    {explanation.narrative}
                  </p>
                ) : null}
                <FactorBarChart
                  data={explanation.top_contributions.map((entry) => ({
                    feature: entry.feature,
                    value: Math.abs(entry.contribution),
                  }))}
                  valueLabel="Attribution"
                  height={Math.max(150, explanation.top_contributions.length * 30)}
                />
                {explanation.fallback_reason ? (
                  <Alert variant="warning">
                    <AlertTitle>Fallback in use</AlertTitle>
                    <AlertDescription>{explanation.fallback_reason}</AlertDescription>
                  </Alert>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}

        <div className="space-y-3 border-t border-white/[0.06] pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="label-muted">Side-by-side model agreement</p>
            <Button
              size="sm"
              variant="outline"
              loading={compare.isFetching}
              onClick={() => void compare.refetch()}
              data-testid="compare-models"
            >
              Compare all models
            </Button>
          </div>
          {compare.isError ? (
            <ErrorPanel error={compare.error} onRetry={() => void compare.refetch()} />
          ) : null}
          {compare.data ? (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead>Forecast</TableHead>
                    <TableHead className="text-right">P(elevated)</TableHead>
                    <TableHead className="text-right">Inference</TableHead>
                    <TableHead>Explanation</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compare.data.results.map((entry) => (
                    <TableRow key={entry.model_name}>
                      <TableCell className="font-mono text-xs">
                        {entry.model_name}
                        {entry.model_version ? (
                          <span className="ml-1 text-muted-foreground">{entry.model_version}</span>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        {entry.error ?? entry.unavailable_reason ? (
                          <span className="text-xs text-destructive">
                            {entry.error ?? entry.unavailable_reason}
                          </span>
                        ) : (
                          <RiskBadge category={entry.predicted_category} />
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {entry.risk_probability === undefined
                          ? '—'
                          : formatPercent(entry.risk_probability, 1)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {entry.inference_ms === undefined
                          ? '—'
                          : `${formatNumber(entry.inference_ms, 2)} ms`}
                      </TableCell>
                      <TableCell className="text-[0.68rem] text-muted-foreground">
                        {entry.explanation_method ?? '—'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
                {compare.data.note}
              </p>
            </>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
