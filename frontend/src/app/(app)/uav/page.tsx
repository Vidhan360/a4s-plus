'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BatteryMedium,
  Home,
  Pause,
  PlaneTakeoff,
  Play,
  Radio,
  RadioTower,
  SatelliteDish,
} from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/page-header';
import { useSimulationStatus } from '@/components/layout/simulation-controls';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { ScrollArea } from '@/components/ui/scroll-area';
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
import { PERM } from '@/lib/constants';
import { formatInt, formatNumber, formatRelative, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Drone, DroneEvent, SwarmStatus } from '@/lib/types';

const FORMATIONS = ['LINE', 'WEDGE', 'COLUMN', 'DIAMOND'] as const;
const COMMANDS = [
  { action: 'LAUNCH', label: 'Launch', icon: PlaneTakeoff },
  { action: 'RESUME', label: 'Resume', icon: Play },
  { action: 'HOLD', label: 'Hold', icon: Pause },
  { action: 'RTB', label: 'Return to base', icon: Home },
  { action: 'LAND', label: 'Land', icon: SatelliteDish },
] as const;

const STATUS_VARIANT: Record<string, 'low' | 'moderate' | 'high' | 'critical' | 'outline'> = {
  ACTIVE: 'low',
  RETURNING: 'moderate',
  OFFLINE: 'outline',
  JAMMED: 'critical',
  ALERT: 'high',
};

/** Renders the swarm on a normalised plan-view canvas with reported-vs-true positions. */
function SwarmMap({ drones, formation }: { drones: Drone[]; formation: string }) {
  const size = 64;
  return (
    <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-white/[0.08] bg-[radial-gradient(circle_at_50%_50%,rgba(56,189,248,0.08),transparent_70%)]">
      <svg viewBox={`0 0 ${size} ${size}`} className="size-full" role="img" aria-label="Swarm plan view" data-testid="swarm-map">
        {Array.from({ length: 9 }, (_, i) => (
          <g key={i} stroke="rgba(255,255,255,0.05)" strokeWidth={0.15}>
            <line x1={(i * size) / 8} y1={0} x2={(i * size) / 8} y2={size} />
            <line x1={0} y1={(i * size) / 8} x2={size} y2={(i * size) / 8} />
          </g>
        ))}
        {drones.map((d) => {
          const spoofed =
            d.under_spoofing && d.reported_grid_x !== null && d.reported_grid_y !== null;
          const color =
            d.status === 'JAMMED'
              ? '#f87171'
              : d.status === 'ALERT'
                ? '#fbbf24'
                : d.status === 'OFFLINE'
                  ? '#64748b'
                  : '#38bdf8';
          return (
            <g key={d.id}>
              {spoofed ? (
                <>
                  <line
                    x1={d.grid_x}
                    y1={d.grid_y}
                    x2={d.reported_grid_x!}
                    y2={d.reported_grid_y!}
                    stroke="#f472b6"
                    strokeWidth={0.25}
                    strokeDasharray="1 1"
                  />
                  <circle
                    cx={d.reported_grid_x!}
                    cy={d.reported_grid_y!}
                    r={0.9}
                    fill="none"
                    stroke="#f472b6"
                    strokeWidth={0.3}
                  />
                </>
              ) : null}
              <circle cx={d.grid_x} cy={d.grid_y} r={1.1} fill={color} />
              <text
                x={d.grid_x + 1.8}
                y={d.grid_y + 0.6}
                fill="rgba(255,255,255,0.65)"
                fontSize={1.9}
              >
                {d.call_sign}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="pointer-events-none absolute bottom-2 left-3 text-[0.65rem] text-muted-foreground">
        Formation {titleCase(formation)} · pink ring = spoofed reported position
      </div>
    </div>
  );
}

/** UAV swarm operations: telemetry, formations, commands and link-attack injection. */
export default function UavPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canCommand = can(PERM.droneCommand);
  const canSimulate = can(PERM.securitySimulate);
  const { data: simStatus } = useSimulationStatus(can(PERM.simulationRead));
  const running = simStatus?.status === 'RUNNING';

  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  const swarm = useQuery<SwarmStatus>({
    queryKey: qk.drones,
    queryFn: () => api.get<SwarmStatus>('/drones'),
    refetchInterval: running ? 4000 : false,
  });

  const events = useQuery<DroneEvent[]>({
    queryKey: qk.droneEvents,
    queryFn: () => api.get<DroneEvent[]>('/drones/events', { limit: 40 }),
    refetchInterval: running ? 6000 : false,
  });

  const drones = swarm.data?.drones ?? [];
  const selected = drones.find((d) => d.id === selectedId) ?? drones[0] ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.drones });
    void queryClient.invalidateQueries({ queryKey: qk.droneEvents });
    void queryClient.invalidateQueries({ queryKey: qk.securityPosture });
  };

  const command = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post<Record<string, unknown>>(`/drones/${id}/command`, { action }),
    onSuccess: (_data, vars) => {
      toast.success(`${vars.action} acknowledged`, {
        description: 'Simulated command applied to the swarm model.',
      });
      invalidate();
    },
    onError: (error) => toast.error('Command rejected', { description: errorMessage(error) }),
  });

  const formationMutation = useMutation({
    mutationFn: (formation: string) =>
      api.post<Record<string, unknown>>('/drones/formation', { formation }),
    onSuccess: (_d, formation) => {
      toast.success(`Formation set to ${titleCase(formation)}`);
      invalidate();
    },
    onError: (error) => toast.error('Formation change failed', { description: errorMessage(error) }),
  });

  const inject = useMutation({
    mutationFn: ({ kind, id }: { kind: 'jamming' | 'spoofing'; id: string }) =>
      api.post<Record<string, unknown>>(`/drones/inject/${kind}`, {
        drone_id: id,
        duration_seconds: 300,
      }),
    onSuccess: (_d, vars) => {
      toast.warning(`${titleCase(vars.kind)} injected`, {
        description: 'A simulated security event was raised for the security monitor.',
      });
      invalidate();
      void queryClient.invalidateQueries({ queryKey: ['security'] });
    },
    onError: (error) => toast.error('Injection failed', { description: errorMessage(error) }),
  });

  const counts = swarm.data?.counts ?? {};
  const meanBattery =
    drones.length > 0 ? drones.reduce((sum, d) => sum + d.battery_pct, 0) / drones.length : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="UAV swarm operations"
        description="Simulated reconnaissance swarm. Telemetry, formation geometry and link degradation are produced by the simulation engine — no real aircraft is connected or commanded by this prototype."
        actions={
          <>
            <Select
              value={swarm.data?.formation ?? 'LINE'}
              onValueChange={(v) => formationMutation.mutate(v)}
              disabled={!canCommand || !running || formationMutation.isPending}
            >
              <SelectTrigger className="w-40" data-testid="formation-select" aria-label="Formation">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FORMATIONS.map((f) => (
                  <SelectItem key={f} value={f}>
                    {titleCase(f)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        }
      />

      {!running ? (
        <Alert>
          <RadioTower />
          <AlertTitle>Simulation engine idle</AlertTitle>
          <AlertDescription>
            Swarm telemetry only advances while the simulation is running, and the backend rejects
            commands, formation changes and attack injection with a 422 when it is stopped. Start a
            run from the Simulation page first.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Airframes"
          value={formatInt(drones.length)}
          hint={`${formatInt(counts.ACTIVE ?? 0)} active · ${formatInt(counts.OFFLINE ?? 0)} offline`}
          icon={PlaneTakeoff}
          loading={swarm.isLoading}
        />
        <StatCard
          label="Mean battery"
          value={`${formatNumber(meanBattery, 1)}%`}
          hint="Simulated discharge model"
          icon={BatteryMedium}
          accent={meanBattery < 30 ? 'high' : 'low'}
          loading={swarm.isLoading}
        />
        <StatCard
          label="Jammed links"
          value={formatInt(drones.filter((d) => d.under_jamming).length)}
          hint="Comms degraded or denied"
          icon={Radio}
          accent="critical"
          loading={swarm.isLoading}
        />
        <StatCard
          label="Spoofed positions"
          value={formatInt(drones.filter((d) => d.under_spoofing).length)}
          hint="Reported position ≠ true position"
          icon={SatelliteDish}
          accent="high"
          loading={swarm.isLoading}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="glass">
          <CardHeader>
            <CardTitle>Swarm plan view</CardTitle>
            <CardDescription>
              Normalised 64 × 64 operating grid shared with the terrain model
            </CardDescription>
          </CardHeader>
          <CardContent>
            {swarm.isLoading ? (
              <LoadingPanel label="Loading swarm…" rows={6} />
            ) : swarm.error ? (
              <ErrorPanel error={swarm.error} onRetry={() => swarm.refetch()} />
            ) : drones.length === 0 ? (
              <EmptyState title="No drones registered" description="Seed the database to create the demo swarm." />
            ) : (
              <SwarmMap drones={drones} formation={swarm.data!.formation} />
            )}
          </CardContent>
        </Card>

        <Card className="glass">
          <CardHeader>
            <CardTitle>Airframe control</CardTitle>
            <CardDescription>
              {selected ? `${selected.call_sign} · ${selected.model}` : 'Select an airframe'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="drone-select">Airframe</Label>
              <Select
                value={selected?.id ?? ''}
                onValueChange={setSelectedId}
                disabled={drones.length === 0}
              >
                <SelectTrigger id="drone-select" data-testid="drone-select">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {drones.map((d) => (
                    <SelectItem key={d.id} value={d.id}>
                      {d.call_sign} — {titleCase(d.status)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {selected ? (
              <>
                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Status</span>
                    <Badge variant={STATUS_VARIANT[selected.status] ?? 'outline'}>
                      {titleCase(selected.status)}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Comms</span>
                    <span className="font-mono">{titleCase(selected.comms_status)}</span>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Battery</span>
                      <span className="font-mono">{formatNumber(selected.battery_pct, 1)}%</span>
                    </div>
                    <Progress value={selected.battery_pct} />
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Signal</span>
                      <span className="font-mono">
                        {formatNumber(selected.signal_strength * 100, 0)}%
                      </span>
                    </div>
                    <Progress value={selected.signal_strength * 100} />
                  </div>
                  {(
                    [
                      ['Altitude', `${formatInt(selected.altitude_m)} m`],
                      ['Speed', `${formatNumber(selected.speed_mps, 1)} m/s`],
                      ['Heading', `${formatInt(selected.heading_deg)}°`],
                      ['True grid', `(${selected.grid_x}, ${selected.grid_y})`],
                      [
                        'Reported grid',
                        selected.reported_grid_x !== null
                          ? `(${selected.reported_grid_x}, ${selected.reported_grid_y})`
                          : 'matches true',
                      ],
                      ['Autonomous', selected.autonomous_mode ? 'yes' : 'no'],
                      ['Last telemetry', formatRelative(selected.last_telemetry_at)],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between">
                      <span className="text-muted-foreground">{k}</span>
                      <span className="font-mono">{v}</span>
                    </div>
                  ))}
                </div>

                <div className="space-y-2 border-t border-white/[0.07] pt-3">
                  <p className="label-muted">Commands</p>
                  <div className="flex flex-wrap gap-2">
                    {COMMANDS.map(({ action, label, icon: Icon }) => (
                      <Button
                        key={action}
                        size="sm"
                        variant="outline"
                        disabled={!canCommand || !running || command.isPending}
                        onClick={() => command.mutate({ id: selected.id, action })}
                        data-testid={`drone-cmd-${action.toLowerCase()}`}
                      >
                        <Icon />
                        {label}
                      </Button>
                    ))}
                  </div>
                </div>

                <div className="space-y-2 border-t border-white/[0.07] pt-3">
                  <p className="label-muted">Simulated link attacks</p>
                  <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                    Injects a fault into the swarm model so the detection and response path can be
                    demonstrated. Nothing is transmitted; no real RF or GNSS signal is involved.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!canSimulate || !running || inject.isPending}
                      onClick={() => inject.mutate({ kind: 'jamming', id: selected.id })}
                      data-testid="inject-jamming"
                    >
                      <Radio />
                      Inject jamming
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!canSimulate || !running || inject.isPending}
                      onClick={() => inject.mutate({ kind: 'spoofing', id: selected.id })}
                      data-testid="inject-spoofing"
                    >
                      <SatelliteDish />
                      Inject GNSS spoofing
                    </Button>
                  </div>
                </div>
              </>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="glass">
          <CardHeader>
            <CardTitle>Telemetry table</CardTitle>
            <CardDescription>{swarm.data?.notice}</CardDescription>
          </CardHeader>
          <CardContent className="px-0">
            {drones.length === 0 ? (
              <EmptyState title="No telemetry" />
            ) : (
              <Table data-testid="drone-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Call sign</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Comms</TableHead>
                    <TableHead className="text-right">Battery</TableHead>
                    <TableHead className="text-right">Alt</TableHead>
                    <TableHead className="text-right">Grid</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drones.map((d) => (
                    <TableRow
                      key={d.id}
                      className="cursor-pointer"
                      onClick={() => setSelectedId(d.id)}
                    >
                      <TableCell className="font-medium">{d.call_sign}</TableCell>
                      <TableCell>
                        <Badge variant={STATUS_VARIANT[d.status] ?? 'outline'}>
                          {titleCase(d.status)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {titleCase(d.comms_status)}
                        {d.under_spoofing ? ' · spoofed' : ''}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatNumber(d.battery_pct, 0)}%
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatInt(d.altitude_m)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        ({d.grid_x}, {d.grid_y})
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="glass">
          <CardHeader>
            <CardTitle>Swarm event log</CardTitle>
            <CardDescription>Most recent simulated events</CardDescription>
          </CardHeader>
          <CardContent>
            {events.isLoading ? (
              <LoadingPanel label="Loading events…" />
            ) : events.error ? (
              <ErrorPanel error={events.error} onRetry={() => events.refetch()} />
            ) : (events.data?.length ?? 0) === 0 ? (
              <EmptyState
                title="No swarm events"
                description="Events appear once the simulation runs or an attack is injected."
              />
            ) : (
              <ScrollArea className="h-[22rem] pr-3">
                <ol className="space-y-3" data-testid="drone-events">
                  {events.data!.map((e) => (
                    <li key={e.id} className="flex gap-3 text-xs">
                      <span className="mt-1 size-1.5 shrink-0 rounded-full bg-primary" />
                      <div className="min-w-0 space-y-0.5">
                        <p className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{titleCase(e.event_type)}</span>
                          <Badge variant={STATUS_VARIANT[e.severity.toUpperCase()] ?? 'outline'}>
                            {titleCase(e.severity)}
                          </Badge>
                        </p>
                        <p className="text-muted-foreground">{e.message}</p>
                        <p className="text-[0.65rem] text-muted-foreground/70">
                          {formatRelative(e.created_at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </ScrollArea>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
