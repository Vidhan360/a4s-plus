'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Cpu, Gauge, HardDriveDownload, History, Play, RotateCcw, Square } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/page-header';
import { DEFAULT_SEED, useSimulationStatus } from '@/components/layout/simulation-controls';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
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
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { errorMessage } from '@/lib/api-error';
import { PERM, SIM_SPEEDS } from '@/lib/constants';
import { formatDateTime, formatDuration, formatInt, formatNumber } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { SimulationStatus } from '@/lib/types';

interface ScenarioCatalogue {
  scenarios: { code: string; label: string; description: string }[];
  speeds: number[];
  notice: string;
}

interface DataSourceInfo {
  active: Record<string, unknown> & { kind: string; name?: string; description?: string };
  declared_but_not_implemented: { name: string; kind: string; status: string; note: string }[];
}

interface SimulationRun {
  id: string;
  scenario: string;
  seed: number;
  speed: number;
  status: string;
  tick_count: number;
  readings_emitted: number;
  alerts_raised: number;
  started_at: string | null;
  stopped_at: string | null;
}

interface SnapshotResponse {
  count: number;
  sim_clock_seconds: number;
  samples: Record<string, string | number | null>[];
  provenance: string;
}

export default function SimulationPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const mayControl = can(PERM.simulationControl);

  const [scenario, setScenario] = React.useState('MIXED');
  const [seed, setSeed] = React.useState(String(DEFAULT_SEED));
  const [speed, setSpeed] = React.useState('2');
  const [tickSeconds, setTickSeconds] = React.useState('5');
  const [simSecondsPerTick, setSimSecondsPerTick] = React.useState('60');

  const status = useSimulationStatus(can(PERM.simulationRead));

  const scenarios = useQuery({
    queryKey: qk.simulationScenarios,
    queryFn: () => api.get<ScenarioCatalogue>('/simulation/scenarios'),
    enabled: can(PERM.simulationRead),
    staleTime: 5 * 60_000,
  });

  const runs = useQuery({
    queryKey: qk.simulationRuns,
    queryFn: () => api.get<SimulationRun[]>('/simulation/runs', { limit: 12 }),
    enabled: can(PERM.simulationRead),
    refetchInterval: 20_000,
  });

  const dataSource = useQuery({
    queryKey: qk.simulationDataSource,
    queryFn: () => api.get<DataSourceInfo>('/simulation/data-source'),
    enabled: can(PERM.simulationRead),
    staleTime: 5 * 60_000,
  });

  const snapshot = useQuery({
    queryKey: ['simulation', 'snapshot'],
    queryFn: () => api.get<SnapshotResponse>('/simulation/snapshot'),
    enabled: false,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['simulation'] });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const control = useMutation({
    mutationFn: (input: { action: string; body?: unknown }) =>
      api.post<SimulationStatus>(`/simulation/${input.action}`, input.body ?? {}),
    onSuccess: (data, input) => {
      queryClient.setQueryData(qk.simulationStatus, data);
      invalidate();
      toast.success(`Simulation ${input.action}`, { description: `Engine state: ${data.status}` });
    },
    onError: (error) => toast.error('Control failed', { description: errorMessage(error) }),
  });

  if (!can(PERM.simulationRead)) {
    return <EmptyState title="Your role does not include the simulation module" />;
  }

  const current = status.data;
  const running = current?.status === 'RUNNING';

  return (
    <div className="space-y-6">
      <PageHeader
        title="Simulation engine"
        description="Everything this system reacts to is produced here. The engine advances a deterministic physiological model for each soldier, a shared environment model and a UAV swarm model. The same seed always reproduces the same trajectory."
        actions={<Badge variant={running ? 'low' : 'secondary'}>{current?.status ?? 'IDLE'}</Badge>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Ticks completed"
          value={formatInt(current?.tick_count)}
          testId="sim-ticks"
          hint={`${formatNumber(current?.last_tick_duration_ms, 1)} ms last tick`}
          icon={Cpu}
          loading={status.isLoading}
        />
        <StatCard
          label="Readings emitted"
          value={formatInt(current?.readings_emitted)}
          hint={`${formatInt(current?.tracked_personnel)} personnel tracked`}
          loading={status.isLoading}
        />
        <StatCard
          label="Alerts raised"
          value={formatInt(current?.alerts_raised)}
          accent={(current?.alerts_raised ?? 0) > 0 ? 'high' : 'muted'}
          loading={status.isLoading}
        />
        <StatCard
          label="Simulated clock"
          value={formatDuration(current?.sim_clock_seconds)}
          hint={
            current?.sim_clock_iso
              ? `In-world time ${formatDateTime(current.sim_clock_iso)}`
              : undefined
          }
          icon={Gauge}
          loading={status.isLoading}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Run configuration</CardTitle>
            <CardDescription>
              {scenarios.data?.notice ??
                'Scenarios drive a physiological model, not recorded patient data.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="sim-scenario">Scenario</Label>
                <Select value={scenario} onValueChange={setScenario} disabled={!mayControl}>
                  <SelectTrigger id="sim-scenario">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(scenarios.data?.scenarios ?? []).map((entry) => (
                      <SelectItem key={entry.code} value={entry.code}>
                        {entry.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
                  {scenarios.data?.scenarios.find((entry) => entry.code === scenario)?.description}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-seed">Seed</Label>
                <Input
                  id="sim-seed"
                  type="number"
                  min={0}
                  value={seed}
                  disabled={!mayControl}
                  onChange={(event) => setSeed(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-speed">Speed</Label>
                <Select value={speed} onValueChange={setSpeed} disabled={!mayControl}>
                  <SelectTrigger id="sim-speed">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SIM_SPEEDS.map((entry) => (
                      <SelectItem key={entry} value={String(entry)}>
                        {entry}×
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-tick">Wall seconds per tick</Label>
                <Input
                  id="sim-tick"
                  type="number"
                  step="0.5"
                  min={0.5}
                  max={60}
                  value={tickSeconds}
                  disabled={!mayControl}
                  onChange={(event) => setTickSeconds(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="sim-sim-seconds">Simulated seconds per tick</Label>
                <Input
                  id="sim-sim-seconds"
                  type="number"
                  step="5"
                  min={5}
                  max={900}
                  value={simSecondsPerTick}
                  disabled={!mayControl}
                  onChange={(event) => setSimSecondsPerTick(event.target.value)}
                />
              </div>
            </div>

            {!mayControl ? (
              <Alert>
                <AlertTitle>Read-only</AlertTitle>
                <AlertDescription>
                  Your role can observe the engine but not drive it. Driving requires
                  simulation:control.
                </AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <Button
                disabled={!mayControl || control.isPending}
                onClick={() =>
                  control.mutate({
                    action: 'start',
                    body: {
                      scenario,
                      seed: Number(seed),
                      speed: Number(speed),
                      tick_seconds: Number(tickSeconds),
                      sim_seconds_per_tick: Number(simSecondsPerTick),
                      reset_first: true,
                    },
                  })
                }
                data-testid="sim-start"
              >
                <Play />
                Start run
              </Button>
              <Button
                variant="outline"
                disabled={!mayControl || control.isPending}
                onClick={() => control.mutate({ action: running ? 'pause' : 'resume' })}
                data-testid="sim-pause-resume"
              >
                {running ? 'Pause' : 'Resume'}
              </Button>
              <Button
                variant="outline"
                disabled={!mayControl || control.isPending}
                onClick={() => control.mutate({ action: 'stop' })}
                data-testid="sim-stop"
              >
                <Square />
                Stop
              </Button>
              <Button
                variant="ghost"
                disabled={!mayControl || control.isPending}
                onClick={() => control.mutate({ action: 'reset' })}
                data-testid="sim-reset"
              >
                <RotateCcw />
                Reset
              </Button>
              <Button
                variant="ghost"
                loading={snapshot.isFetching}
                onClick={() => void snapshot.refetch()}
              >
                <HardDriveDownload />
                Probe snapshot
              </Button>
            </div>

            {current?.scenario_assignments &&
            Object.keys(current.scenario_assignments).length > 0 ? (
              <div className="space-y-2">
                <p className="label-muted">Per-soldier scenario assignment</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(current.scenario_assignments).map(([person, assigned]) => (
                    <Badge key={person} variant="outline" className="font-mono">
                      {person.slice(0, 8)} · {assigned}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card data-testid="data-source-panel">
          <CardHeader>
            <CardTitle>
              Data source — the hardware seam
            </CardTitle>
            <CardDescription>
              The application only ever talks to a <span className="font-mono">DataSource</span>.
              Swapping simulation for hardware means implementing one interface, not redesigning the
              system.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {dataSource.isLoading ? (
              <LoadingPanel rows={3} />
            ) : dataSource.isError ? (
              <ErrorPanel error={dataSource.error} onRetry={() => void dataSource.refetch()} />
            ) : (
              <>
                <div className="rounded-lg border border-primary/25 bg-primary/[0.07] px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-semibold text-primary">Active source</p>
                    <Badge>{dataSource.data?.active.kind}</Badge>
                  </div>
                  <p className="mt-1 text-[0.7rem] leading-relaxed text-muted-foreground">
                    {String(
                      dataSource.data?.active.description ??
                        dataSource.data?.active.name ??
                        'Simulation data source',
                    )}
                  </p>
                </div>
                <div className="space-y-2">
                  <p className="label-muted">Declared but not implemented</p>
                  {(dataSource.data?.declared_but_not_implemented ?? []).map((entry) => (
                    <div
                      key={entry.name}
                      className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs">{entry.name}</p>
                        <Badge variant="outline">{entry.status}</Badge>
                      </div>
                      <p className="mt-1 text-[0.68rem] leading-relaxed text-muted-foreground">
                        {entry.note}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {snapshot.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Instantaneous probe</CardTitle>
            <CardDescription>
              A read-only sample of the current simulated instant. It does not advance the clock, so
              you can call it repeatedly without perturbing the run. Provenance:{' '}
              {snapshot.data.provenance}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Personnel</TableHead>
                  <TableHead className="text-right">SpO₂</TableHead>
                  <TableHead className="text-right">HR</TableHead>
                  <TableHead className="text-right">Resp</TableHead>
                  <TableHead className="text-right">Temp</TableHead>
                  <TableHead className="text-right">Altitude</TableHead>
                  <TableHead>Scenario</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {snapshot.data.samples.map((sample, index) => (
                  <TableRow key={index}>
                    <TableCell className="font-mono text-[0.68rem]">
                      {String(sample.personnel_id).slice(0, 8)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(Number(sample.spo2), 1)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(Number(sample.heart_rate), 0)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(Number(sample.respiratory_rate), 1)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(Number(sample.body_temp_c), 1)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatNumber(Number(sample.altitude_m), 0)}
                    </TableCell>
                    <TableCell className="text-[0.68rem] text-muted-foreground">
                      {String(sample.scenario ?? '—')}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="size-3.5 text-primary" />
            Run history
          </CardTitle>
          <CardDescription>
            Every run is persisted with its seed, so any result shown in a demo can be reproduced
            exactly.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {runs.isLoading ? (
            <LoadingPanel rows={4} />
          ) : runs.isError ? (
            <ErrorPanel error={runs.error} onRetry={() => void runs.refetch()} />
          ) : (runs.data?.length ?? 0) === 0 ? (
            <EmptyState
              title="No runs recorded yet"
              description="Start a run above and it will be logged here with its seed and counters."
            />
          ) : (
            <Table data-testid="run-history">
              <TableHeader>
                <TableRow>
                  <TableHead>Scenario</TableHead>
                  <TableHead className="text-right">Seed</TableHead>
                  <TableHead className="text-right">Speed</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Ticks</TableHead>
                  <TableHead className="text-right">Readings</TableHead>
                  <TableHead className="text-right">Alerts</TableHead>
                  <TableHead className="text-right">Started</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs.data ?? []).map((run) => (
                  <TableRow key={run.id}>
                    <TableCell className="text-xs">{run.scenario}</TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {run.seed}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {run.speed}×
                    </TableCell>
                    <TableCell>
                      <Badge variant={run.status === 'RUNNING' ? 'low' : 'secondary'}>
                        {run.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatInt(run.tick_count)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatInt(run.readings_emitted)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {formatInt(run.alerts_raised)}
                    </TableCell>
                    <TableCell className="text-right text-[0.68rem] text-muted-foreground">
                      {formatDateTime(run.started_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
