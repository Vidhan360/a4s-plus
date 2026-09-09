'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Boxes,
  ClipboardPlus,
  HeartPulse,
  MapPin,
  Siren,
  Thermometer,
} from 'lucide-react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import * as React from 'react';
import { toast } from 'sonner';

import { RiskTrendChart } from '@/components/charts/risk-trend-chart';
import { VitalsChart } from '@/components/charts/vitals-chart';
import { PredictionPanel } from '@/components/domain/prediction-panel';
import { ProvenanceChip } from '@/components/domain/provenance';
import { RiskBadge } from '@/components/domain/risk-badge';
import { WhyThisRisk } from '@/components/domain/why-this-risk';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
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
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { ApiError, errorMessage } from '@/lib/api-error';
import { PERM } from '@/lib/constants';
import { formatDateTime, formatNumber, formatRelative } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { PersonnelDetail } from '@/lib/types';

const INGEST_FIELDS = [
  { key: 'heart_rate', label: 'Heart rate (bpm)', value: '128' },
  { key: 'spo2', label: 'SpO₂ (%)', value: '82' },
  { key: 'body_temp_c', label: 'Body temperature (°C)', value: '35.1' },
  { key: 'respiratory_rate', label: 'Respiratory rate (/min)', value: '28' },
  { key: 'bp_systolic', label: 'Systolic BP (mmHg)', value: '148' },
  { key: 'bp_diastolic', label: 'Diastolic BP (mmHg)', value: '96' },
  { key: 'altitude_m', label: 'Altitude (m)', value: '5600' },
  { key: 'fatigue_score', label: 'Fatigue (0–100)', value: '78' },
  { key: 'env_temp_c', label: 'Ambient temperature (°C)', value: '-19' },
  { key: 'wind_kph', label: 'Wind (km/h)', value: '44' },
] as const;

function ManualIngestDialog({ personnelId, onDone }: { personnelId: string; onDone: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [values, setValues] = React.useState<Record<string, string>>(
    Object.fromEntries(INGEST_FIELDS.map((field) => [field.key, field.value])),
  );
  const [error, setError] = React.useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<{ risk: { score: number; category: string }; alerts: unknown[] }>('/vitals/ingest', {
        personnel_id: personnelId,
        ...Object.fromEntries(
          INGEST_FIELDS.map((field) => [field.key, Number(values[field.key])]),
        ),
      }),
    onSuccess: (data) => {
      toast.success(`Reading recorded — risk ${data.risk.category}`, {
        description: `Score ${formatNumber(data.risk.score, 1)}/100. Provenance is stamped MANUAL, not SIMULATION.`,
      });
      setOpen(false);
      onDone();
    },
    onError: (err) => {
      const fields = err instanceof ApiError ? Object.values(err.fieldErrors) : [];
      setError(fields[0] ?? errorMessage(err));
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="manual-ingest">
        <ClipboardPlus />
        Record a reading
      </Button>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Record an observation manually</DialogTitle>
          <DialogDescription>
            The server stamps this reading as <span className="font-mono">MANUAL</span> and marks it
            as not simulated, so the provenance stays honest. It is scored by the same rule engine
            as simulated telemetry.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
          onSubmit={(event) => {
            event.preventDefault();
            setError(null);
            mutation.mutate();
          }}
        >
          {INGEST_FIELDS.map((field) => (
            <div key={field.key} className="space-y-1.5">
              <Label htmlFor={`ingest-${field.key}`}>{field.label}</Label>
              <Input
                id={`ingest-${field.key}`}
                type="number"
                step="0.1"
                required
                value={values[field.key] ?? ''}
                onChange={(event) =>
                  setValues((previous) => ({ ...previous, [field.key]: event.target.value }))
                }
              />
            </div>
          ))}
          {error ? (
            <p className="text-xs text-destructive sm:col-span-2 lg:col-span-3" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter className="sm:col-span-2 lg:col-span-3">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Record and score
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function PersonnelDetailPage() {
  const params = useParams<{ id: string }>();
  const personnelId = params.id;
  const { can } = useSession();
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: qk.person(personnelId),
    queryFn: () => api.get<PersonnelDetail>(`/personnel/${personnelId}`, { history_limit: 180 }),
    enabled: can(PERM.personnelRead),
    refetchInterval: 20_000,
  });

  if (!can(PERM.personnelRead)) {
    return <EmptyState title="Your role does not include the roster" />;
  }

  if (detail.isLoading) return <LoadingPanel rows={10} />;
  if (detail.isError) {
    return <ErrorPanel error={detail.error} onRetry={() => void detail.refetch()} />;
  }
  if (!detail.data) return <EmptyState title="Soldier not found" />;

  const { personnel, readings, risk_history, open_alerts, twin } = detail.data;
  const latest = readings[0];
  const risk = twin?.state.risk;

  const riskTimeline = [...risk_history]
    .slice(-90)
    .map((entry) => ({
      bucket: entry.created_at,
      mean_risk: entry.risk_score,
      samples: 1,
    }));

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${personnel.call_sign} — ${personnel.name}`}
        description={
          <>
            {personnel.rank ? `${personnel.rank}, ` : ''}
            {personnel.unit} · age {personnel.age} · baseline HR{' '}
            {personnel.baseline_heart_rate} bpm, baseline SpO₂ {personnel.baseline_spo2}% ·
            scenario {personnel.sim_scenario ?? 'not assigned'}
          </>
        }
        actions={
          <>
            <Button asChild size="sm" variant="ghost">
              <Link href="/personnel">
                <ArrowLeft />
                Roster
              </Link>
            </Button>
            <ProvenanceChip source={latest?.source} />
            {can(PERM.vitalsIngest) ? (
              <ManualIngestDialog
                personnelId={personnelId}
                onDone={() => {
                  void queryClient.invalidateQueries({ queryKey: ['personnel'] });
                }}
              />
            ) : null}
            <Button asChild size="sm" variant="outline">
              <Link href={`/personnel/${personnelId}/twin`}>
                <Boxes />
                Digital twin
              </Link>
            </Button>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Current risk"
          value={risk ? formatNumber(risk.score, 1) : '—'}
          hint={risk ? risk.category : 'No assessment yet'}
          icon={HeartPulse}
          accent={
            risk?.category === 'CRITICAL'
              ? 'critical'
              : risk?.category === 'HIGH'
                ? 'high'
                : risk?.category === 'MODERATE'
                  ? 'moderate'
                  : 'low'
          }
        />
        <StatCard
          label="SpO₂"
          value={latest ? formatNumber(latest.spo2, 1) : '—'}
          hint={latest ? `baseline ${personnel.baseline_spo2}%` : undefined}
          icon={HeartPulse}
          accent={(latest?.spo2 ?? 100) < 90 ? 'critical' : 'low'}
        />
        <StatCard
          label="Heart rate"
          value={latest ? formatNumber(latest.heart_rate, 0) : '—'}
          hint={latest ? `baseline ${personnel.baseline_heart_rate} bpm` : undefined}
          icon={HeartPulse}
          accent={(latest?.heart_rate ?? 0) > 120 ? 'high' : 'primary'}
        />
        <StatCard
          label="Open alerts"
          value={open_alerts.length}
          hint={
            latest ? `Last reading ${formatRelative(latest.recorded_at)}` : 'No telemetry recorded'
          }
          icon={Siren}
          accent={open_alerts.length > 0 ? 'critical' : 'muted'}
        />
      </div>

      {!latest ? (
        <EmptyState
          title="No telemetry for this soldier yet"
          description="Start the simulation from the top bar, or record an observation manually, and the risk engine will score it immediately."
        />
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {risk ? <WhyThisRisk risk={risk} /> : null}
        <PredictionPanel personnelId={personnelId} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Telemetry history</CardTitle>
          <CardDescription>
            Newest {readings.length} readings for this soldier. All simulated unless the provenance
            chip says otherwise.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="oxygen">
            <TabsList>
              <TabsTrigger value="oxygen">Oxygen &amp; heart</TabsTrigger>
              <TabsTrigger value="respiration">Respiration &amp; temp</TabsTrigger>
              <TabsTrigger value="pressure">Blood pressure</TabsTrigger>
              <TabsTrigger value="environment">Altitude &amp; environment</TabsTrigger>
              <TabsTrigger value="risk">Risk history</TabsTrigger>
            </TabsList>
            <TabsContent value="oxygen">
              <VitalsChart
                readings={readings}
                keys={['spo2', 'heart_rate']}
                reference={{ value: 90, label: 'SpO₂ warning band' }}
              />
            </TabsContent>
            <TabsContent value="respiration">
              <VitalsChart readings={readings} keys={['respiratory_rate', 'body_temp_c']} />
            </TabsContent>
            <TabsContent value="pressure">
              <VitalsChart readings={readings} keys={['bp_systolic', 'bp_diastolic']} />
            </TabsContent>
            <TabsContent value="environment">
              <VitalsChart
                readings={readings}
                keys={['altitude_m', 'env_temp_c', 'wind_kph', 'fatigue_score']}
              />
            </TabsContent>
            <TabsContent value="risk">
              <RiskTrendChart data={riskTimeline} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Siren className="size-3.5 text-primary" />
              Open alerts
            </CardTitle>
            <CardDescription>
              Raised by the alert engine after deduplication and cooldown.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {open_alerts.length === 0 ? (
              <EmptyState title="No open alerts" className="border-0 py-8" />
            ) : (
              <ul className="space-y-2">
                {open_alerts.map((alert) => (
                  <li
                    key={alert.id}
                    className="space-y-1 rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <p className="text-xs font-medium">{alert.title}</p>
                      <RiskBadge category={alert.severity} />
                    </div>
                    <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                      {alert.reason}
                    </p>
                    <p className="text-[0.68rem] text-primary">{alert.recommended_action}</p>
                    <p className="text-[0.65rem] text-muted-foreground/70">
                      {formatRelative(alert.last_triggered_at)} · seen ×{alert.occurrence_count}
                      {alert.escalated_from ? ` · escalated from ${alert.escalated_from}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MapPin className="size-3.5 text-primary" />
              Latest sample
            </CardTitle>
            <CardDescription>
              Exactly what the risk engine was given for the current score.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {latest ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Channel</TableHead>
                    <TableHead className="text-right">Value</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {[
                    ['Recorded at', formatDateTime(latest.recorded_at)],
                    ['SpO₂', `${formatNumber(latest.spo2, 1)} %`],
                    ['Heart rate', `${formatNumber(latest.heart_rate, 0)} bpm`],
                    ['Respiratory rate', `${formatNumber(latest.respiratory_rate, 1)} /min`],
                    ['Body temperature', `${formatNumber(latest.body_temp_c, 1)} °C`],
                    [
                      'Blood pressure',
                      `${formatNumber(latest.bp_systolic, 0)}/${formatNumber(latest.bp_diastolic, 0)} mmHg`,
                    ],
                    ['Fatigue', formatNumber(latest.fatigue_score, 1)],
                    ['Activity level', latest.activity_level],
                    ['Altitude', `${formatNumber(latest.altitude_m, 0)} m`],
                    ['Ambient temperature', `${formatNumber(latest.env_temp_c, 1)} °C`],
                    ['Wind', `${formatNumber(latest.wind_kph, 1)} km/h`],
                    [
                      'Grid position',
                      latest.grid_x === null ? '—' : `${latest.grid_x}, ${latest.grid_y}`,
                    ],
                    ['Source', latest.source],
                    ['Scenario', latest.scenario ?? '—'],
                  ].map(([label, value]) => (
                    <TableRow key={label}>
                      <TableCell className="text-xs text-muted-foreground">{label}</TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {value}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No sample yet" icon={Thermometer} className="border-0 py-8" />
            )}
          </CardContent>
        </Card>
      </div>

      {twin?.state.provenance ? (
        <div className="flex flex-wrap items-center gap-2 text-[0.68rem] text-muted-foreground">
          <Badge variant="outline">source {twin.state.provenance.source}</Badge>
          <Badge variant="outline">
            simulated {twin.state.provenance.is_simulated ? 'yes' : 'no'}
          </Badge>
          <span>{twin.state.provenance.disclaimer}</span>
        </div>
      ) : null}
    </div>
  );
}
