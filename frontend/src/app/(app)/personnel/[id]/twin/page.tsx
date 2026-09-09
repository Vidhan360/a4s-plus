'use client';

import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Boxes, Clock, Radio } from 'lucide-react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import * as React from 'react';

import { ProbabilityChart } from '@/components/charts/probability-chart';
import { VitalsChart } from '@/components/charts/vitals-chart';
import { ProvenanceChip } from '@/components/domain/provenance';
import { RiskBadge } from '@/components/domain/risk-badge';
import { WhyThisRisk } from '@/components/domain/why-this-risk';
import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { PERM } from '@/lib/constants';
import { formatDateTime, formatDuration, formatNumber, formatPercent } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { DigitalTwin, VitalReading } from '@/lib/types';

/** The twin history series is a compact projection, so adapt it for the chart. */
function toReadings(series: DigitalTwin['state']['history']['series']): VitalReading[] {
  return series.map((entry, index) => ({
    id: index,
    personnel_id: '',
    recorded_at: entry.recorded_at,
    heart_rate: entry.heart_rate,
    spo2: entry.spo2,
    body_temp_c: entry.body_temp_c,
    respiratory_rate: entry.respiratory_rate,
    bp_systolic: 0,
    bp_diastolic: 0,
    altitude_m: entry.altitude_m,
    fatigue_score: entry.fatigue_score,
    activity_level: '',
    env_temp_c: 0,
    wind_kph: 0,
    latitude: 0,
    longitude: 0,
    grid_x: null,
    grid_y: null,
    source: 'SIMULATION',
    scenario: null,
  }));
}

export default function DigitalTwinPage() {
  const params = useParams<{ id: string }>();
  const personnelId = params.id;
  const { can } = useSession();

  const twin = useQuery({
    queryKey: qk.personTwin(personnelId),
    queryFn: () => api.get<DigitalTwin>(`/personnel/${personnelId}/twin`),
    enabled: can(PERM.personnelRead),
    refetchInterval: 10_000,
  });

  if (!can(PERM.personnelRead)) return <EmptyState title="Your role does not include this view" />;
  if (twin.isLoading) return <LoadingPanel rows={10} />;
  if (twin.isError) {
    return <ErrorPanel error={twin.error} onRetry={() => void twin.refetch()} />;
  }
  if (!twin.data) return <EmptyState title="No twin available" />;

  const { state } = twin.data;
  // `series` is ordered oldest-first by the API; VitalsChart reverses it, so
  // hand it the newest-first order it expects.
  const readings = toReadings([...state.history.series].reverse());

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Digital twin — ${twin.data.call_sign}`}
        description="A single materialised view of one soldier: latest vitals, environment, position, explained risk, forecast and open alerts. Recomputed on every ingest and cached for fast reads."
        actions={
          <>
            <Button asChild size="sm" variant="ghost">
              <Link href={`/personnel/${personnelId}`}>
                <ArrowLeft />
                Detail view
              </Link>
            </Button>
            <ProvenanceChip source={state.provenance.source} />
            <RiskBadge category={twin.data.risk_category} score={twin.data.risk_score} pulse />
          </>
        }
      />

      {twin.data.is_stale ? (
        <Alert variant="warning" data-testid="twin-stale">
          <Clock />
          <AlertTitle>This twin is stale</AlertTitle>
          <AlertDescription>
            The last telemetry is {formatDuration(state.vitals.age_seconds)} old. Start or resume the
            simulation to refresh it.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Boxes className="size-3.5 text-primary" />
              Soldier
            </CardTitle>
            <CardDescription>Identity and acclimatisation baselines.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="space-y-1.5">
              {[
                ['Call sign', state.personnel.call_sign],
                ['Name', state.personnel.name],
                ['Rank', state.personnel.rank ?? '—'],
                ['Unit', state.personnel.unit],
                ['Age', String(state.personnel.age)],
                ['Status', state.personnel.status],
                ['Baseline HR', `${state.personnel.baseline_heart_rate} bpm`],
                ['Baseline SpO₂', `${state.personnel.baseline_spo2} %`],
              ].map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-3">
                  <dt className="label-muted">{label}</dt>
                  <dd className="font-mono text-[0.7rem] tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Latest vitals</CardTitle>
            <CardDescription>
              Recorded {formatDateTime(state.vitals.recorded_at)} ·{' '}
              {formatDuration(state.vitals.age_seconds)} old
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Channel</TableHead>
                  <TableHead className="text-right">Value</TableHead>
                  <TableHead className="text-right">Δ baseline</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(
                  [
                    ['spo2', 'SpO₂', '%'],
                    ['heart_rate', 'Heart rate', 'bpm'],
                    ['respiratory_rate', 'Respiratory rate', '/min'],
                    ['body_temp_c', 'Body temperature', '°C'],
                    ['bp_systolic', 'Systolic BP', 'mmHg'],
                    ['bp_diastolic', 'Diastolic BP', 'mmHg'],
                    ['fatigue_score', 'Fatigue', ''],
                  ] as const
                ).map(([key, label, unit]) => (
                  <TableRow key={key}>
                    <TableCell className="text-xs text-muted-foreground">{label}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(state.vitals[key] as number, 1)} {unit}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                      {state.vitals.deltas?.[key] === undefined
                        ? '—'
                        : `${state.vitals.deltas[key] > 0 ? '+' : ''}${formatNumber(state.vitals.deltas[key], 1)}`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Environment &amp; position</CardTitle>
            <CardDescription>{state.environment.wind_chill_note}</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="space-y-1.5">
              {[
                ['Altitude', `${formatNumber(state.environment.altitude_m, 0)} m`],
                ['Ambient temperature', `${formatNumber(state.environment.env_temp_c, 1)} °C`],
                ['Wind', `${formatNumber(state.environment.wind_kph, 1)} km/h`],
                [
                  'Grid cell',
                  state.location.grid_x === null
                    ? '—'
                    : `${state.location.grid_x}, ${state.location.grid_y}`,
                ],
                ['Latitude', formatNumber(state.location.latitude, 5)],
                ['Longitude', formatNumber(state.location.longitude, 5)],
                ['Activity level', state.vitals.activity_level],
                ['Scenario', state.provenance.scenario ?? '—'],
              ].map(([label, value]) => (
                <div key={label} className="flex items-baseline justify-between gap-3">
                  <dt className="label-muted">{label}</dt>
                  <dd className="font-mono text-[0.7rem] tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <WhyThisRisk risk={state.risk} />

        <Card>
          <CardHeader>
            <CardTitle>Cached forecast</CardTitle>
            <CardDescription>
              Produced during the last ingest for this soldier — not re-run on page load.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {state.prediction ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <RiskBadge category={state.prediction.predicted_category} pulse />
                  <Badge variant="secondary">
                    {state.prediction.model_name} {state.prediction.model_version}
                  </Badge>
                  <Badge variant="outline">{state.prediction.explanation_method}</Badge>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    P(elevated) {formatPercent(state.prediction.risk_probability, 1)} ·{' '}
                    {state.prediction.horizon_minutes} min horizon
                  </span>
                </div>

                {state.prediction.class_probabilities ? (
                  <ProbabilityChart probabilities={state.prediction.class_probabilities} />
                ) : null}

                {state.prediction.narrative ? (
                  <p className="text-xs leading-relaxed">{state.prediction.narrative}</p>
                ) : null}

                <div className="rounded-lg border border-primary/25 bg-primary/[0.07] px-4 py-3">
                  <p className="label-muted text-primary">Recommended action</p>
                  <p className="mt-1 text-xs leading-relaxed">
                    {state.prediction.recommended_action}
                  </p>
                </div>

                {state.prediction.top_contributions.length > 0 ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Channel</TableHead>
                        <TableHead className="text-right">Value</TableHead>
                        <TableHead className="text-right">Attribution</TableHead>
                        <TableHead>Direction</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {state.prediction.top_contributions.map((entry) => (
                        <TableRow key={entry.feature}>
                          <TableCell className="text-xs">{entry.label}</TableCell>
                          <TableCell className="text-right font-mono text-xs tabular-nums">
                            {formatNumber(entry.value, 2)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs tabular-nums">
                            {formatNumber(entry.contribution, 4)}
                          </TableCell>
                          <TableCell className="text-[0.68rem] text-muted-foreground">
                            {entry.direction}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : null}
              </>
            ) : (
              <EmptyState
                title="No cached forecast"
                description="A prediction is stored on the twin as soon as enough telemetry exists for the model's input window."
                className="border-0"
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radio className="size-3.5 text-primary" />
            Twin history ({state.history.samples} samples)
          </CardTitle>
          <CardDescription>
            The exact window the twin keeps for trend detection and model input.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <VitalsChart readings={readings} keys={['spo2', 'heart_rate', 'respiratory_rate']} />
        </CardContent>
      </Card>

      <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
        {state.provenance.disclaimer}
      </p>
    </div>
  );
}
