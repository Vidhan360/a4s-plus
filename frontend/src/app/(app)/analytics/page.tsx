'use client';

import { useQuery } from '@tanstack/react-query';
import { Activity, BarChart3, Clock, FlaskConical } from 'lucide-react';
import * as React from 'react';

import { FactorBarChart } from '@/components/charts/factor-bar-chart';
import { ModelComparisonChart } from '@/components/charts/model-comparison-chart';
import { RiskDistributionChart } from '@/components/charts/risk-distribution-chart';
import { RiskTrendChart } from '@/components/charts/risk-trend-chart';
import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { StatCard } from '@/components/ui/stat-card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { api } from '@/lib/api-client';
import { formatDuration, formatInt, formatNumber, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Analytics, ModelComparison } from '@/lib/types';

const WINDOWS = [
  { value: '1', label: 'Last hour' },
  { value: '6', label: 'Last 6 hours' },
  { value: '24', label: 'Last 24 hours' },
  { value: '72', label: 'Last 3 days' },
  { value: '168', label: 'Last 7 days' },
];

const MODEL_LABELS: Record<string, string> = {
  rule_baseline: 'Rule baseline',
  lstm: 'LSTM (PyTorch)',
  gradient_boosting: 'Gradient boosting',
};

/** Analytics and model evaluation. Every metric shown here is measured, never asserted. */
export default function AnalyticsPage() {
  const [hours, setHours] = React.useState('24');

  const analytics = useQuery<Analytics>({
    queryKey: qk.analytics(Number(hours)),
    queryFn: () => api.get<Analytics>('/analytics', { window_hours: Number(hours) }),
  });

  const comparison = useQuery<ModelComparison>({
    queryKey: qk.modelComparison,
    queryFn: () => api.get<ModelComparison>('/analytics/model-comparison'),
    staleTime: 30 * 60 * 1000,
  });

  const a = analytics.data;

  const best = React.useMemo(() => {
    const models = comparison.data?.models ?? [];
    if (models.length === 0) return null;
    return [...models].sort((x, y) => (y.macro_f1 ?? 0) - (x.macro_f1 ?? 0))[0];
  }, [comparison.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics &amp; model evaluation"
        description="Operational analytics over simulated telemetry, plus the measured evaluation of every risk model on a held-out, subject-disjoint test split. No metric on this page is hardcoded — all of it comes from the training run recorded in the model registry."
        actions={
          <Select value={hours} onValueChange={setHours}>
            <SelectTrigger className="w-40" data-testid="analytics-window" aria-label="Time window">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOWS.map((w) => (
                <SelectItem key={w.value} value={w.value}>
                  {w.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />

      {analytics.isLoading ? (
        <LoadingPanel label="Aggregating telemetry…" rows={6} />
      ) : analytics.error ? (
        <ErrorPanel error={analytics.error} onRetry={() => analytics.refetch()} />
      ) : a ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Readings analysed"
              value={formatInt(a.readings)}
              hint={`${a.window_hours} h window`}
              icon={Activity}
            />
            <StatCard
              label="Risk samples"
              value={formatInt(a.risk_timeline.reduce((s, b) => s + b.samples, 0))}
              hint={`${a.risk_timeline.length} buckets`}
              icon={BarChart3}
            />
            <StatCard
              label="Mean time to acknowledge"
              value={
                a.mean_time_to_acknowledge_seconds === null
                  ? 'n/a'
                  : formatDuration(a.mean_time_to_acknowledge_seconds)
              }
              hint={
                a.mean_time_to_acknowledge_seconds === null
                  ? 'No acknowledged alerts in window'
                  : 'Alert raised → acknowledged'
              }
              icon={Clock}
            />
            <StatCard
              label="Best macro F1"
              value={best ? formatNumber(best.macro_f1, 4) : '—'}
              hint={best ? MODEL_LABELS[best.model] ?? best.model : 'Evaluation unavailable'}
              icon={FlaskConical}
              accent="primary"
            />
          </div>

          <Tabs defaultValue="operations">
            <TabsList>
              <TabsTrigger value="operations">Operations</TabsTrigger>
              <TabsTrigger value="models" data-testid="tab-models">
                Model evaluation
              </TabsTrigger>
              <TabsTrigger value="signals">Signal analysis</TabsTrigger>
            </TabsList>

            <TabsContent value="operations" className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
                <Card className="glass">
                  <CardHeader>
                    <CardTitle>Risk over time</CardTitle>
                    <CardDescription>Mean and peak population risk per bucket</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {a.risk_timeline.length === 0 ? (
                      <EmptyState
                        title="No risk samples in this window"
                        description="Start the simulation or widen the window."
                      />
                    ) : (
                      <RiskTrendChart data={a.risk_timeline} />
                    )}
                  </CardContent>
                </Card>
                <Card className="glass">
                  <CardHeader>
                    <CardTitle>Risk distribution</CardTitle>
                    <CardDescription>Assessment categories in window</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <RiskDistributionChart distribution={a.risk_distribution} />
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Card className="glass">
                  <CardHeader>
                    <CardTitle>Alerts by type</CardTitle>
                    <CardDescription>Counts within the selected window</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {Object.keys(a.alerts_by_type).length === 0 ? (
                      <EmptyState title="No alerts in window" />
                    ) : (
                      <div className="space-y-2">
                        {Object.entries(a.alerts_by_type)
                          .sort((x, y) => y[1] - x[1])
                          .map(([type, count]) => {
                            const max = Math.max(...Object.values(a.alerts_by_type));
                            return (
                              <div key={type} className="space-y-1">
                                <div className="flex items-center justify-between text-xs">
                                  <span>{titleCase(type)}</span>
                                  <span className="font-mono text-muted-foreground">
                                    {formatInt(count)}
                                  </span>
                                </div>
                                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                                  <div
                                    className="h-full rounded-full bg-primary/70"
                                    style={{ width: `${(count / max) * 100}%` }}
                                  />
                                </div>
                              </div>
                            );
                          })}
                      </div>
                    )}
                  </CardContent>
                </Card>

                <Card className="glass">
                  <CardHeader>
                    <CardTitle>Top risk drivers</CardTitle>
                    <CardDescription>
                      Summed factor contributions across all assessments in window
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {a.top_risk_factors.length === 0 ? (
                      <EmptyState title="No factor data" />
                    ) : (
                      <FactorBarChart
                        data={a.top_risk_factors.map((f) => ({
                          feature: f.key,
                          value: f.total_contribution,
                        }))}
                        valueLabel="Total contribution"
                      />
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card className="glass">
                <CardHeader>
                  <CardTitle>Per-person summary</CardTitle>
                  <CardDescription>Risk statistics per tracked individual</CardDescription>
                </CardHeader>
                <CardContent className="px-0">
                  {a.per_person.length === 0 ? (
                    <EmptyState title="No personnel telemetry in window" />
                  ) : (
                    <Table data-testid="per-person">
                      <TableHeader>
                        <TableRow>
                          <TableHead>Call sign</TableHead>
                          <TableHead>Scenario</TableHead>
                          <TableHead className="text-right">Samples</TableHead>
                          <TableHead className="text-right">Mean risk</TableHead>
                          <TableHead className="text-right">Peak risk</TableHead>
                          <TableHead className="text-right">Latest</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {a.per_person.map((p) => (
                          <TableRow key={p.personnel_id}>
                            <TableCell className="font-medium">{p.call_sign}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {p.scenario ? titleCase(p.scenario) : '—'}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatInt(p.samples)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatNumber(p.mean_risk, 1)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatNumber(p.peak_risk, 1)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatNumber(p.latest_risk, 1)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="models" className="space-y-4">
              <Alert>
                <FlaskConical />
                <AlertTitle>How these numbers were produced</AlertTitle>
                <AlertDescription>
                  {comparison.data?.caveats?.join(' ') ??
                    'Metrics are read from the recorded training run.'}
                </AlertDescription>
              </Alert>

              {comparison.isLoading ? (
                <LoadingPanel label="Loading evaluation…" rows={5} />
              ) : comparison.error ? (
                <ErrorPanel error={comparison.error} onRetry={() => comparison.refetch()} />
              ) : comparison.data && comparison.data.models.length > 0 ? (
                <>
                  <Card className="glass">
                    <CardHeader>
                      <CardTitle>Measured comparison</CardTitle>
                      <CardDescription>
                        Source: {comparison.data.source} · {formatInt(comparison.data.models[0].n_samples)} held-out
                        test sequences
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ModelComparisonChart models={comparison.data.models} />
                    </CardContent>
                  </Card>

                  <Card className="glass">
                    <CardHeader>
                      <CardTitle>Full metric table</CardTitle>
                      <CardDescription>
                        “Elevated” collapses HIGH and CRITICAL into a single positive class, which is
                        the decision the operator actually cares about.
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="overflow-x-auto px-0">
                      <Table data-testid="model-metrics">
                        <TableHeader>
                          <TableRow>
                            <TableHead>Model</TableHead>
                            <TableHead className="text-right">Accuracy</TableHead>
                            <TableHead className="text-right">Macro F1</TableHead>
                            <TableHead className="text-right">Weighted F1</TableHead>
                            <TableHead className="text-right">Elevated F1</TableHead>
                            <TableHead className="text-right">Elevated recall</TableHead>
                            <TableHead className="text-right">ROC AUC</TableHead>
                            <TableHead className="text-right">Brier</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {comparison.data.models.map((m) => (
                            <TableRow key={m.model}>
                              <TableCell className="font-medium">
                                {MODEL_LABELS[m.model] ?? m.model}
                                {best?.model === m.model ? (
                                  <Badge variant="low" className="ml-2">
                                    best macro F1
                                  </Badge>
                                ) : null}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatNumber(m.accuracy, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatNumber(m.macro_f1, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatNumber(m.weighted_f1, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatNumber(m.elevated_f1, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {formatNumber(m.elevated_recall, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {m.elevated_roc_auc === null
                                  ? 'n/a'
                                  : formatNumber(m.elevated_roc_auc, 4)}
                              </TableCell>
                              <TableCell className="text-right font-mono">
                                {m.brier_score_elevated === null
                                  ? 'n/a'
                                  : formatNumber(m.brier_score_elevated, 4)}
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </CardContent>
                  </Card>

                  <div className="grid gap-4 lg:grid-cols-3">
                    {comparison.data.models
                      .filter((m) => m.confusion_matrix && m.confusion_matrix_labels)
                      .map((m) => (
                      <Card key={m.model} className="glass">
                        <CardHeader>
                          <CardTitle className="text-sm">
                            {MODEL_LABELS[m.model] ?? m.model}
                          </CardTitle>
                          <CardDescription>Confusion matrix (rows = truth)</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-3">
                          <div className="overflow-x-auto">
                            <table className="w-full border-collapse text-[0.65rem]">
                              <thead>
                                <tr>
                                  <th />
                                  {m.confusion_matrix_labels!.map((l) => (
                                    <th
                                      key={l}
                                      className="px-1 py-1 text-center font-medium text-muted-foreground"
                                    >
                                      {l.slice(0, 4)}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {m.confusion_matrix!.map((row, i) => {
                                  const rowTotal = row.reduce((s, v) => s + v, 0) || 1;
                                  return (
                                    <tr key={i}>
                                      <th className="pr-2 text-right font-medium text-muted-foreground">
                                        {m.confusion_matrix_labels![i]?.slice(0, 4)}
                                      </th>
                                      {row.map((v, j) => (
                                        <td
                                          key={j}
                                          className="px-1 py-1 text-center font-mono"
                                          style={{
                                            background:
                                              i === j
                                                ? `rgba(56,189,248,${0.08 + (v / rowTotal) * 0.42})`
                                                : `rgba(248,113,113,${(v / rowTotal) * 0.4})`,
                                          }}
                                        >
                                          {v}
                                        </td>
                                      ))}
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                          <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                            {m.note}
                          </p>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                </>
              ) : (
                <EmptyState
                  title="No evaluation artefacts found"
                  description="Run the training pipeline to generate a measured comparison. Until then the API reports the models as unavailable rather than inventing metrics."
                />
              )}
            </TabsContent>

            <TabsContent value="signals" className="space-y-4">
              <Card className="glass">
                <CardHeader>
                  <CardTitle>Vital-sign correlation with risk score</CardTitle>
                  <CardDescription>
                    Pearson r computed over the readings in this window. Correlation on simulated
                    data reflects the generator&rsquo;s design, not clinical evidence.
                  </CardDescription>
                </CardHeader>
                <CardContent className="px-0">
                  {a.vitals_correlation.length === 0 ? (
                    <EmptyState title="Not enough paired samples" />
                  ) : (
                    <Table data-testid="correlation-table">
                      <TableHeader>
                        <TableRow>
                          <TableHead>Channel</TableHead>
                          <TableHead className="text-right">Pearson r</TableHead>
                          <TableHead className="text-right">Samples</TableHead>
                          <TableHead>Interpretation</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {a.vitals_correlation.map((c) => (
                          <TableRow key={c.channel}>
                            <TableCell className="font-medium">{c.label}</TableCell>
                            <TableCell className="text-right font-mono">
                              {c.pearson_r === null ? 'n/a' : formatNumber(c.pearson_r, 3)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatInt(c.samples)}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">{c.note}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>

              <Card className="glass">
                <CardHeader>
                  <CardTitle>Factor breakdown detail</CardTitle>
                  <CardDescription>
                    Occurrence counts and mean contribution per risk factor
                  </CardDescription>
                </CardHeader>
                <CardContent className="px-0">
                  {a.top_risk_factors.length === 0 ? (
                    <EmptyState title="No factor data" />
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Factor</TableHead>
                          <TableHead className="text-right">Occurrences</TableHead>
                          <TableHead className="text-right">Mean contribution</TableHead>
                          <TableHead className="text-right">Total contribution</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {a.top_risk_factors.map((f) => (
                          <TableRow key={f.key}>
                            <TableCell className="font-medium">{f.label}</TableCell>
                            <TableCell className="text-right font-mono">
                              {formatInt(f.occurrences)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatNumber(f.mean_contribution, 2)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {formatNumber(f.total_contribution, 1)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <Card className="glass">
            <CardHeader>
              <CardTitle>Data honesty</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              {Object.entries(a.disclaimer).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <Badge variant="outline" className="shrink-0">
                    {titleCase(k)}
                  </Badge>
                  <span className="leading-relaxed text-muted-foreground">{String(v)}</span>
                </div>
              ))}
              <p className="pt-1 text-muted-foreground">
                Model metrics source: <code className="font-mono">{a.model_metrics_source}</code>
              </p>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
