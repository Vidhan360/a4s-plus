'use client';

import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Boxes,
  CircleCheck,
  CircleX,
  Cpu,
  Database,
  Info,
  Radio,
  ShieldQuestion,
} from 'lucide-react';
import * as React from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
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
import { API_BASE_URL } from '@/lib/api-client';
import { api } from '@/lib/api-client';
import { DISCLAIMERS } from '@/lib/constants';
import { formatDuration, formatInt, formatNumber, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { HealthStatus, ModelDescription, ServiceMeta } from '@/lib/types';

interface DataSourceInfo {
  active: Record<string, unknown> & { kind: string; name?: string; description?: string };
  declared_but_not_implemented: { name: string; kind: string; status: string; note: string }[];
}

function Capability({ granted, label }: { granted: boolean; label: string }) {
  return (
    <li className="flex items-start gap-2 text-xs">
      {granted ? (
        <CircleCheck className="mt-0.5 size-4 shrink-0 text-risk-low" />
      ) : (
        <CircleX className="mt-0.5 size-4 shrink-0 text-muted-foreground/60" />
      )}
      <span className={granted ? '' : 'text-muted-foreground'}>{label}</span>
    </li>
  );
}

const CAPABILITY_LABELS: Record<string, string> = {
  real_sensors: 'Reads real physiological sensors',
  real_uav_control: 'Commands real UAV hardware',
  clinical_validation: 'Clinically validated for medical use',
  encrypted_data_at_rest: 'Application data encrypted at rest',
  authenticated_encryption_demo: 'Authenticated encryption demonstration (AES-256-GCM)',
};

/** System status, honest capability declaration and the hardware-integration seam. */
export default function AdminSystemPage() {
  const meta = useQuery<ServiceMeta>({
    queryKey: qk.meta,
    queryFn: () => api.get<ServiceMeta>('/meta'),
    staleTime: 60 * 60 * 1000,
  });

  const health = useQuery<HealthStatus>({
    queryKey: qk.health,
    queryFn: () => api.get<HealthStatus>('/health'),
    refetchInterval: 15000,
  });

  const models = useQuery<ModelDescription[]>({
    queryKey: qk.models,
    queryFn: () => api.get<ModelDescription[]>('/predictions/models'),
  });

  const dataSource = useQuery<DataSourceInfo>({
    queryKey: qk.simulationDataSource,
    queryFn: () => api.get<DataSourceInfo>('/simulation/data-source'),
  });

  const ok = health.data?.status === 'ok';

  return (
    <div className="space-y-6">
      <PageHeader
        title="System status"
        description="Live service health, the honest capability declaration served by the API itself, the model registry and the hardware-integration seam."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Service"
          value={ok ? 'Healthy' : (health.data?.status ?? 'Unknown')}
          hint={`v${health.data?.version ?? '—'} · ${health.data?.environment ?? '—'}`}
          icon={Activity}
          accent={ok ? 'low' : 'critical'}
          loading={health.isLoading}
        />
        <StatCard
          label="Database"
          value={titleCase(health.data?.database ?? 'unknown')}
          hint="PostgreSQL via SQLAlchemy async"
          icon={Database}
          accent={health.data?.database === 'ok' ? 'low' : 'critical'}
          loading={health.isLoading}
        />
        <StatCard
          label="Event bus"
          value={health.data?.event_bus ?? '—'}
          hint="Redis pub/sub, with an in-process fallback"
          icon={Radio}
          loading={health.isLoading}
        />
        <StatCard
          label="Uptime"
          value={
            health.data ? formatDuration(health.data.uptime_seconds) : '—'
          }
          hint="Since process start"
          icon={Cpu}
          loading={health.isLoading}
        />
      </div>

      <Alert>
        <ShieldQuestion />
        <AlertTitle>{meta.data?.prototype_status ?? DISCLAIMERS.prototype}</AlertTitle>
        <AlertDescription>
          {meta.data
            ? `Data mode: ${meta.data.data_mode}. Validation status: ${meta.data.validation_status}.`
            : DISCLAIMERS.data}
        </AlertDescription>
      </Alert>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="glass">
          <CardHeader>
            <CardTitle>Capability declaration</CardTitle>
            <CardDescription>
              Served by <code className="font-mono">GET /meta</code>. Anything unchecked is not
              implemented and is not claimed anywhere in this product.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {meta.isLoading ? (
              <LoadingPanel label="Loading capabilities…" />
            ) : meta.error ? (
              <ErrorPanel error={meta.error} onRetry={() => meta.refetch()} />
            ) : (
              <ul className="space-y-2" data-testid="capabilities">
                {Object.entries(meta.data?.capabilities ?? {}).map(([key, value]) => (
                  <Capability
                    key={key}
                    granted={value}
                    label={CAPABILITY_LABELS[key] ?? titleCase(key)}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="glass">
          <CardHeader>
            <CardTitle>Disclaimers</CardTitle>
            <CardDescription>Emitted with every health and metadata response</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {Object.entries(meta.data?.disclaimer ?? health.data?.disclaimer ?? {}).map(
              ([k, v]) => (
                <div key={k} className="flex gap-2">
                  <Badge variant="outline" className="shrink-0">
                    {titleCase(k)}
                  </Badge>
                  <span className="leading-relaxed text-muted-foreground">{String(v)}</span>
                </div>
              ),
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="glass">
        <CardHeader>
          <CardTitle>Model registry</CardTitle>
          <CardDescription>
            Models the prediction API will actually serve. An untrained model is reported as
            unavailable with a reason rather than silently falling back.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {models.isLoading ? (
            <LoadingPanel label="Loading models…" />
          ) : models.error ? (
            <ErrorPanel error={models.error} onRetry={() => models.refetch()} />
          ) : (models.data?.length ?? 0) === 0 ? (
            <EmptyState title="No models registered" />
          ) : (
            <Table data-testid="model-registry">
              <TableHeader>
                <TableRow>
                  <TableHead>Model</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Available</TableHead>
                  <TableHead>Explainability</TableHead>
                  <TableHead className="text-right">Horizon</TableHead>
                  <TableHead className="text-right">Sequence</TableHead>
                  <TableHead className="text-right">Macro F1</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.data!.map((m) => {
                  const macroF1 = m.metrics?.['macro_f1'];
                  return (
                    <TableRow key={m.name}>
                      <TableCell className="font-medium">{m.name}</TableCell>
                      <TableCell className="font-mono text-xs">{m.version}</TableCell>
                      <TableCell>
                        <Badge variant={m.available ? 'low' : 'outline'}>
                          {m.available ? 'Ready' : 'Unavailable'}
                        </Badge>
                        {m.unavailable_reason ? (
                          <p className="mt-1 max-w-xs text-[0.65rem] text-muted-foreground">
                            {m.unavailable_reason}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell className="max-w-xs text-xs text-muted-foreground">
                        {m.explanation_method}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatInt(m.horizon_minutes)} min
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatInt(m.sequence_length)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {typeof macroF1 === 'number' ? formatNumber(macroF1, 4) : 'n/a'}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="glass">
          <CardHeader>
            <CardTitle>Active data source</CardTitle>
            <CardDescription>
              Telemetry enters through one interface. Swapping in hardware means registering a new
              implementation of that interface — no engine, schema or UI change.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {dataSource.isLoading ? (
              <LoadingPanel label="Loading data source…" />
            ) : dataSource.error ? (
              <ErrorPanel error={dataSource.error} onRetry={() => dataSource.refetch()} />
            ) : dataSource.data ? (
              <div className="space-y-3 text-xs" data-testid="data-source">
                <dl className="space-y-2">
                  {Object.entries(dataSource.data.active).map(([k, v]) => (
                    <div key={k} className="flex items-start justify-between gap-3">
                      <dt className="shrink-0 text-muted-foreground">{titleCase(k)}</dt>
                      <dd className="text-right font-mono">
                        {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="glass">
          <CardHeader>
            <CardTitle>Declared but not implemented</CardTitle>
            <CardDescription>
              Hardware adapters the interface anticipates. They are listed as unimplemented rather
              than stubbed to look real.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {(dataSource.data?.declared_but_not_implemented.length ?? 0) === 0 ? (
              <EmptyState title="Nothing declared" />
            ) : (
              <ul className="space-y-3 text-xs" data-testid="hardware-seam">
                {dataSource.data!.declared_but_not_implemented.map((d) => (
                  <li key={d.name} className="flex gap-3">
                    <Boxes className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                    <div>
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {d.name}
                        <Badge variant="outline">{titleCase(d.status)}</Badge>
                      </p>
                      <p className="leading-relaxed text-muted-foreground">{d.note}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="glass">
        <CardHeader>
          <CardTitle>Runtime detail</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ['Product', meta.data?.name],
                ['Version', meta.data?.version],
                ['Team', meta.data?.team],
                ['Tagline', meta.data?.tagline],
                ['API base URL', API_BASE_URL],
                ['Simulation engine', health.data?.simulation],
                ['ML models loaded', JSON.stringify(health.data?.ml_models ?? {})],
              ] as const
            ).map(([k, v]) => (
              <div key={k}>
                <dt className="label-muted flex items-center gap-1">
                  <Info className="size-3" />
                  {k}
                </dt>
                <dd className="break-all font-mono">{v ?? '—'}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
