'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Boxes,
  BrainCircuit,
  Radio,
  ShieldAlert,
  Siren,
  Thermometer,
  Users,
  Wind,
} from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';

import { RiskDistributionChart } from '@/components/charts/risk-distribution-chart';
import { RiskTrendChart } from '@/components/charts/risk-trend-chart';
import { ProvenanceChip } from '@/components/domain/provenance';
import { RiskBadge } from '@/components/domain/risk-badge';
import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatCard } from '@/components/ui/stat-card';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useLiveStream } from '@/hooks/use-live-stream';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { PERM } from '@/lib/constants';
import { formatInt, formatNumber, formatRelative, formatTime } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Analytics, DashboardSummary } from '@/lib/types';

function LiveFeed() {
  const { events, status } = useLiveStream();

  return (
    <Card className="flex h-full flex-col" data-testid="live-feed" data-stream-status={status}>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <Radio className="size-3.5 text-primary" />
            Live event stream
          </CardTitle>
          <Badge variant={status === 'live' ? 'low' : 'secondary'}>{status}</Badge>
        </div>
        <CardDescription>
          Frames pushed over the WebSocket by the simulation engine, alert engine and security
          monitor.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1">
        {events.length === 0 ? (
          <EmptyState
            title="No events yet"
            description="Start the simulation from the top bar to see telemetry, alerts and UAV events arrive in real time."
            icon={Radio}
            className="border-0"
          />
        ) : (
          <ul className="max-h-[320px] space-y-1.5 overflow-y-auto pr-1" data-testid="live-feed-items">
            {events.slice(0, 40).map((event) => (
              <li
                key={event.id}
                className="flex items-baseline gap-2 rounded-md border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5"
              >
                <span className="font-mono text-[0.62rem] text-muted-foreground">
                  {formatTime(event.ts)}
                </span>
                <Badge variant="outline" className="shrink-0">
                  {event.topic}
                </Badge>
                <span className="truncate text-[0.7rem]">{event.event}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { can, user } = useSession();
  const { snapshot } = useLiveStream();

  const dashboard = useQuery({
    queryKey: qk.dashboard,
    queryFn: () => api.get<DashboardSummary>('/dashboard'),
    enabled: can(PERM.dashboardRead),
    refetchInterval: 20_000,
  });

  const analytics = useQuery({
    queryKey: qk.analytics(6),
    queryFn: () => api.get<Analytics>('/analytics', { hours: 6 }),
    enabled: can(PERM.analyticsRead),
    refetchInterval: 60_000,
  });

  // The WebSocket snapshot is authoritative between polls.
  const data = dashboard.data ?? snapshot ?? undefined;

  if (!can(PERM.dashboardRead)) {
    return (
      <EmptyState
        title="Your role does not include the command dashboard"
        description="Ask an administrator for the dashboard:read permission."
      />
    );
  }

  const drones = data?.drones;
  const security = data?.security;
  const dronesActive = drones?.by_status?.ACTIVE ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Command dashboard`}
        description={
          <>
            Roster-wide risk picture for the simulated deployment, refreshed live.
            {user ? ` Signed in as ${user.full_name}.` : ''}
          </>
        }
        actions={
          <>
            <ProvenanceChip source="SIMULATION" />
            <Button asChild size="sm" variant="outline">
              <Link href="/personnel">Open roster</Link>
            </Button>
          </>
        }
      />

      {dashboard.isError ? (
        <ErrorPanel error={dashboard.error} onRetry={() => void dashboard.refetch()} />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Personnel tracked"
          value={formatInt(data?.personnel_total)}
          hint={data ? `${data.personnel_active} active on the roster` : undefined}
          icon={Users}
          loading={dashboard.isLoading && !data}
        />
        <StatCard
          label="Mean risk score"
          value={formatNumber(data?.average_risk, 1)}
          hint="0–100, rule engine"
          icon={Activity}
          accent={
            (data?.average_risk ?? 0) >= 65
              ? 'high'
              : (data?.average_risk ?? 0) >= 40
                ? 'moderate'
                : 'low'
          }
          loading={dashboard.isLoading && !data}
        />
        <StatCard
          label="Open alerts"
          value={formatInt(data?.open_alerts)}
          hint={`${formatInt(data?.critical_alerts.length)} critical open`}
          icon={Siren}
          accent={(data?.critical_alerts.length ?? 0) > 0 ? 'critical' : 'primary'}
          loading={dashboard.isLoading && !data}
        />
        <StatCard
          label="UAVs airborne"
          value={`${formatInt(dronesActive)} / ${formatInt(drones?.total)}`}
          hint={`${formatInt(drones?.jammed)} jammed · ${formatInt(drones?.spoofed)} spoofed · battery ${formatNumber(drones?.mean_battery_pct, 0)}%`}
          icon={Boxes}
          accent={(drones?.jammed ?? 0) > 0 ? 'high' : 'primary'}
          loading={dashboard.isLoading && !data}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Mean risk over the last 6 hours</CardTitle>
            <CardDescription>
              Bucketed mean of every risk assessment produced in the window. Simulated physiology.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {analytics.isLoading ? (
              <LoadingPanel rows={5} />
            ) : analytics.isError ? (
              <ErrorPanel error={analytics.error} onRetry={() => void analytics.refetch()} />
            ) : (
              <RiskTrendChart data={analytics.data?.risk_timeline ?? []} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Risk distribution</CardTitle>
            <CardDescription>Latest category per person across the roster.</CardDescription>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading && !data ? (
              <LoadingPanel rows={3} />
            ) : (
              <RiskDistributionChart distribution={data?.risk_distribution ?? {}} />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle>Watchlist</CardTitle>
                <CardDescription>
                  Highest current risk first. Open a soldier to see the explained score and the
                  30-minute forecast.
                </CardDescription>
              </div>
              <Button asChild size="sm" variant="ghost">
                <Link href="/personnel">All personnel</Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading && !data ? (
              <LoadingPanel />
            ) : (data?.watchlist.length ?? 0) === 0 ? (
              <EmptyState
                title="Nobody is on the watchlist"
                description="Either no telemetry has been scored yet, or everyone is in the LOW band. Start the simulation to generate activity."
                className="border-0"
              />
            ) : (
              <Table data-testid="watchlist">
                <TableHeader>
                  <TableRow>
                    <TableHead>Call sign</TableHead>
                    <TableHead>Unit</TableHead>
                    <TableHead>Risk</TableHead>
                    <TableHead>Forecast</TableHead>
                    <TableHead className="text-right">SpO₂</TableHead>
                    <TableHead className="text-right">HR</TableHead>
                    <TableHead className="text-right">Alerts</TableHead>
                    <TableHead className="text-right">Updated</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.watchlist ?? []).map((entry) => (
                    <TableRow key={entry.personnel_id}>
                      <TableCell>
                        <Link
                          href={`/personnel/${entry.personnel_id}`}
                          className="font-medium text-primary hover:underline"
                        >
                          {entry.call_sign}
                        </Link>
                        <p className="text-[0.68rem] text-muted-foreground">{entry.name}</p>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{entry.unit}</TableCell>
                      <TableCell>
                        <RiskBadge
                          category={entry.risk_category}
                          score={entry.risk_score}
                          pulse
                        />
                      </TableCell>
                      <TableCell>
                        {entry.predicted_category ? (
                          <RiskBadge category={entry.predicted_category} />
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatNumber(entry.spo2, 1)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {formatNumber(entry.heart_rate, 0)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        {entry.open_alert_count}
                      </TableCell>
                      <TableCell className="text-right text-[0.68rem] text-muted-foreground">
                        {formatRelative(entry.updated_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <LiveFeed />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Wind className="size-3.5 text-primary" />
              Simulated environment
            </CardTitle>
            <CardDescription>Shared conditions driving the physiological model.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {data?.environment ? (
              <dl className="grid grid-cols-2 gap-3">
                {[
                  {
                    label: 'Base temp',
                    value: `${formatNumber(data.environment.base_temp_c, 1)} °C`,
                  },
                  { label: 'Wind', value: `${formatNumber(data.environment.wind_kph, 1)} km/h` },
                  {
                    label: 'Visibility',
                    value: `${formatNumber(data.environment.visibility_km, 1)} km`,
                  },
                  {
                    label: 'Front intensity',
                    value: formatNumber(data.environment.front_intensity, 2),
                  },
                ].map((entry) => (
                  <div key={entry.label}>
                    <dt className="label-muted">{entry.label}</dt>
                    <dd className="font-mono text-sm tabular-nums">{entry.value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <EmptyState
                title="No environment sample"
                description="The environment model publishes once the simulation is running."
                icon={Thermometer}
                className="border-0 py-6"
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BrainCircuit className="size-3.5 text-primary" />
              Prediction models loaded
            </CardTitle>
            <CardDescription>
              Registry state at process start. Metrics live under Analytics.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {(data?.prediction_models.length ?? 0) === 0 ? (
              <EmptyState title="No models registered" className="border-0 py-6" />
            ) : (
              <ul className="space-y-2">
                {(data?.prediction_models ?? []).map((model) => (
                  <li
                    key={model.name}
                    className="flex items-center justify-between gap-2 rounded-md border border-white/[0.05] bg-white/[0.02] px-3 py-2"
                  >
                    <span className="text-xs font-medium">{model.name}</span>
                    <span className="font-mono text-[0.65rem] text-muted-foreground">
                      {model.version}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="size-3.5 text-primary" />
              Security posture
            </CardTitle>
            <CardDescription>
              Real application controls plus any injected demonstration events.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="label-muted">Open events</p>
                <p className="font-mono text-lg tabular-nums">{formatInt(security?.open_events)}</p>
              </div>
              <div>
                <p className="label-muted">Failed sign-ins (24 h)</p>
                <p className="font-mono text-lg tabular-nums text-risk-high">
                  {formatInt(security?.failed_logins_24h)}
                </p>
              </div>
            </div>
            {can(PERM.securityRead) ? (
              <Button asChild size="sm" variant="outline" className="w-full">
                <Link href="/security">Open security monitor</Link>
              </Button>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {data?.disclaimer ? (
        <Alert variant="warning">
          <ShieldAlert />
          <AlertTitle>Data provenance</AlertTitle>
          <AlertDescription>
            {Object.values(data.disclaimer).join(' ')}
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}
