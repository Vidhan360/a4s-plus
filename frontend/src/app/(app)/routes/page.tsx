'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Route as RouteIcon, ShieldCheck, Timer } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/page-header';
import { TerrainCanvas, type TerrainLayer } from '@/components/domain/terrain-canvas';
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
import { Switch } from '@/components/ui/switch';
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
import { formatDateTime, formatInt, formatNumber } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type {
  Paged,
  PathNode,
  RouteCalculation,
  RoutePlanResponse,
  TerrainGrid,
  TerrainMap,
} from '@/lib/types';

/** The canvas draws tuples; the API returns `{x, y}` objects. */
function toPolyline(path: PathNode[] | undefined): [number, number][] | undefined {
  return path?.map((node) => [node.x, node.y] as [number, number]);
}

interface OptimalityResult {
  astar_cost: number;
  dijkstra_cost: number;
  optimal: boolean;
  nodes_expanded_astar: number;
  compute_ms_astar: number;
  interpretation: string;
}

interface StoredRoute {
  id: string;
  name: string;
  start_x: number;
  start_y: number;
  goal_x: number;
  goal_y: number;
  created_at: string;
  calculations: RouteCalculation[];
}

type PickMode = 'start' | 'goal';

const HAZARD_LAYERS = ['avalanche', 'crevasse', 'weather', 'difficulty'] as const;

/** A* safe-route planning with a safest/shortest comparison and an optimality proof. */
export default function RoutesPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canPlan = can(PERM.routePlan);

  const [start, setStart] = React.useState({ x: 4, y: 58 });
  const [goal, setGoal] = React.useState({ x: 56, y: 6 });
  const [pickMode, setPickMode] = React.useState<PickMode>('start');
  const [layer, setLayer] = React.useState<TerrainLayer>('avalanche');
  const [persist, setPersist] = React.useState(true);
  const [layers, setLayers] = React.useState<string[]>([
    'avalanche',
    'crevasse',
    'weather',
    'difficulty',
  ]);
  const [name, setName] = React.useState('Ridge resupply');
  const [plan, setPlan] = React.useState<RoutePlanResponse | null>(null);
  const [hover, setHover] = React.useState<{ x: number; y: number } | null>(null);

  const maps = useQuery<TerrainMap[]>({
    queryKey: qk.terrainMaps,
    queryFn: () => api.get<TerrainMap[]>('/terrain/maps'),
  });
  const mapId = maps.data?.[0]?.id;

  const grid = useQuery<TerrainGrid>({
    queryKey: qk.terrainGrid(mapId),
    queryFn: () => api.get<TerrainGrid>('/terrain/grid', mapId ? { map_id: mapId } : undefined),
    enabled: maps.isSuccess,
    staleTime: 10 * 60 * 1000,
  });

  const history = useQuery<Paged<StoredRoute>>({
    queryKey: qk.routes({ limit: 8 }),
    queryFn: () => api.get<Paged<StoredRoute>>('/routes', { limit: 8, offset: 0 }),
  });

  const planMutation = useMutation({
    mutationFn: () =>
      api.post<RoutePlanResponse>('/routes/plan', {
        start_x: start.x,
        start_y: start.y,
        goal_x: goal.x,
        goal_y: goal.y,
        name,
        persist,
        compare_shortest: true,
        enabled_layers: layers,
        ...(mapId ? { map_id: mapId } : {}),
      }),
    onSuccess: (data) => {
      setPlan(data);
      if (!data.safest.found) {
        toast.warning('No traversable path', {
          description: 'A* exhausted the reachable frontier without reaching the goal.',
        });
      } else {
        toast.success('Route planned', {
          description: `${formatInt(data.safest.distance_m)} m · ${formatInt(data.safest.estimated_minutes)} min`,
        });
      }
      void queryClient.invalidateQueries({ queryKey: ['routes'] });
      void queryClient.invalidateQueries({ queryKey: qk.alertSummary });
    },
    onError: (error) => toast.error('Planning failed', { description: errorMessage(error) }),
  });

  const optimality = useMutation({
    mutationFn: () =>
      api.get<OptimalityResult>('/routes/verify-optimality', {
        start_x: start.x,
        start_y: start.y,
        goal_x: goal.x,
        goal_y: goal.y,
        ...(mapId ? { map_id: mapId } : {}),
      }),
    onError: (error) => toast.error('Verification failed', { description: errorMessage(error) }),
  });

  const hazardLayer = React.useMemo(() => {
    if (!grid.data || layer === 'elevation') return undefined;
    return grid.data[layer];
  }, [grid.data, layer]);

  const onCellClick = (x: number, y: number) => {
    if (pickMode === 'start') {
      setStart({ x, y });
      setPickMode('goal');
    } else {
      setGoal({ x, y });
      setPickMode('start');
    }
  };

  const safest = plan?.safest;
  const shortest = plan?.shortest ?? null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Safe-route planner"
        description="A* search over the synthetic terrain grid. The safest profile weights avalanche, crevasse and weather exposure into the movement cost; the shortest profile optimises distance only, so the two can be compared directly."
        actions={
          <>
            <Select value={layer} onValueChange={(v) => setLayer(v as TerrainLayer)}>
              <SelectTrigger className="w-44" aria-label="Map layer">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="elevation">Elevation</SelectItem>
                <SelectItem value="avalanche">Avalanche risk</SelectItem>
                <SelectItem value="crevasse">Crevasse risk</SelectItem>
                <SelectItem value="weather">Weather exposure</SelectItem>
                <SelectItem value="difficulty">Difficulty</SelectItem>
              </SelectContent>
            </Select>
            <Button
              onClick={() => planMutation.mutate()}
              disabled={!canPlan || planMutation.isPending || !grid.data}
              data-testid="plan-route"
            >
              <RouteIcon />
              {planMutation.isPending ? 'Planning…' : 'Plan route'}
            </Button>
          </>
        }
      />

      {!canPlan ? (
        <Alert>
          <ShieldCheck />
          <AlertTitle>Read-only access</AlertTitle>
          <AlertDescription>
            Your role can view terrain and stored routes but cannot run the planner. Route planning
            requires the <code className="font-mono">route:plan</code> permission.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <Card className="glass">
          <CardHeader>
            <CardTitle>Terrain &amp; computed path</CardTitle>
            <CardDescription>
              Click the map to set the {pickMode === 'start' ? 'start' : 'goal'} cell. Cyan = safest
              route, amber dashed = shortest route.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {grid.isLoading ? (
              <LoadingPanel label="Loading terrain…" rows={6} />
            ) : grid.error ? (
              <ErrorPanel error={grid.error} onRetry={() => grid.refetch()} />
            ) : grid.data ? (
              <>
                <TerrainCanvas
                  width={grid.data.map.width}
                  height={grid.data.map.height}
                  elevation={grid.data.elevation}
                  hazard={hazardLayer}
                  blocked={grid.data.blocked}
                  layer={layer}
                  minElevation={grid.data.map.min_elevation_m}
                  maxElevation={grid.data.map.max_elevation_m}
                  path={safest?.found ? toPolyline(safest.path) : undefined}
                  altPath={shortest?.found ? toPolyline(shortest.path) : undefined}
                  hoverCell={hover}
                  onCellHover={setHover}
                  onCellClick={onCellClick}
                  markers={[
                    { ...start, label: 'S', color: '#22d3ee', shape: 'square' },
                    { ...goal, label: 'G', color: '#f472b6', shape: 'triangle' },
                  ]}
                />
                <p className="mt-3 text-[0.7rem] text-muted-foreground">
                  {hover
                    ? `(${hover.x}, ${hover.y}) · ${formatInt(grid.data.elevation[hover.y]?.[hover.x] ?? 0)} m`
                    : `Start (${start.x}, ${start.y}) → Goal (${goal.x}, ${goal.y})`}
                </p>
              </>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="glass">
            <CardHeader>
              <CardTitle>Plan parameters</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="route-name">Route name</Label>
                <Input id="route-name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="sx">Start X</Label>
                  <Input
                    id="sx"
                    type="number"
                    value={start.x}
                    onChange={(e) => setStart((s) => ({ ...s, x: Number(e.target.value) }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="sy">Start Y</Label>
                  <Input
                    id="sy"
                    type="number"
                    value={start.y}
                    onChange={(e) => setStart((s) => ({ ...s, y: Number(e.target.value) }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="gx">Goal X</Label>
                  <Input
                    id="gx"
                    type="number"
                    value={goal.x}
                    onChange={(e) => setGoal((s) => ({ ...s, x: Number(e.target.value) }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="gy">Goal Y</Label>
                  <Input
                    id="gy"
                    type="number"
                    value={goal.y}
                    onChange={(e) => setGoal((s) => ({ ...s, y: Number(e.target.value) }))}
                  />
                </div>
              </div>
              <div className="space-y-2 pt-1">
                <Label className="text-xs">Hazard layers in the cost function</Label>
                {HAZARD_LAYERS.map((l) => (
                  <div key={l} className="flex items-center justify-between gap-3">
                    <Label
                      htmlFor={`layer-${l}`}
                      className="text-xs font-normal capitalize text-muted-foreground"
                    >
                      {l}
                    </Label>
                    <Switch
                      id={`layer-${l}`}
                      checked={layers.includes(l)}
                      onCheckedChange={(on) =>
                        setLayers((prev) =>
                          on ? [...prev, l] : prev.filter((item) => item !== l),
                        )
                      }
                    />
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="persist" className="text-xs font-normal text-muted-foreground">
                  Save this route to the database
                </Label>
                <Switch id="persist" checked={persist} onCheckedChange={setPersist} />
              </div>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => optimality.mutate()}
                disabled={!canPlan || optimality.isPending}
                data-testid="verify-optimality"
              >
                <CheckCircle2 />
                {optimality.isPending ? 'Verifying…' : 'Verify A* optimality'}
              </Button>
              {optimality.data ? (
                <div
                  className="space-y-1 rounded-md border border-white/[0.08] bg-white/[0.02] p-3 text-xs"
                  data-testid="optimality-result"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">A* cost</span>
                    <span className="font-mono">{formatNumber(optimality.data.astar_cost, 3)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Dijkstra cost</span>
                    <span className="font-mono">
                      {formatNumber(optimality.data.dijkstra_cost, 3)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-muted-foreground">Nodes expanded (A*)</span>
                    <span className="font-mono">
                      {formatInt(optimality.data.nodes_expanded_astar)}
                    </span>
                  </div>
                  <Badge variant={optimality.data.optimal ? 'low' : 'high'}>
                    {optimality.data.optimal ? 'Optimal' : 'Not optimal'}
                  </Badge>
                  <p className="pt-1 leading-relaxed text-muted-foreground">
                    {optimality.data.interpretation}
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {plan ? (
            <Card className="glass">
              <CardHeader>
                <CardTitle>Safest vs shortest</CardTitle>
                <CardDescription>{plan.comparison.optimality_note}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs">
                {Object.entries(plan.comparison.delta).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">{key.replace(/_/g, ' ')}</span>
                    <span className="font-mono">{formatNumber(value, 2)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      {plan ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Distance (safest)"
              value={`${formatInt(safest?.distance_m ?? 0)} m`}
              hint={`${formatInt(safest?.path.length ?? 0)} cells`}
              icon={RouteIcon}
            />
            <StatCard
              label="Estimated time"
              value={`${formatInt(safest?.estimated_minutes ?? 0)} min`}
              hint="Terrain-adjusted movement model"
              icon={Timer}
            />
            <StatCard
              label="Route risk"
              value={formatNumber(safest?.risk_score ?? 0, 3)}
              hint={`Worst cell ${formatNumber(safest?.max_cell_risk ?? 0, 3)}`}
              accent={(safest?.risk_score ?? 0) > 0.5 ? 'high' : 'low'}
            />
            <StatCard
              label="Search cost"
              value={formatInt(safest?.nodes_expanded ?? 0)}
              hint={`nodes expanded in ${formatNumber(safest?.compute_ms ?? 0, 1)} ms`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="glass">
              <CardHeader>
                <CardTitle>Why this route</CardTitle>
                <CardDescription>Explanation emitted by the planner</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-xs leading-relaxed" data-testid="route-explanation">
                  {(safest?.explanation.summary ?? []).map((line, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
                {safest?.avoided_hazards ? (
                  <div className="mt-4 space-y-1 border-t border-white/[0.07] pt-3 text-xs">
                    <p className="label-muted">Hazard exposure along the chosen path</p>
                    {Object.entries(
                      (safest.avoided_hazards.mean ?? {}) as Record<string, number>,
                    ).map(([layer, mean]) => {
                      const peak = (
                        (safest.avoided_hazards.peak ?? {}) as Record<string, number>
                      )[layer];
                      return (
                        <div key={layer} className="flex items-center justify-between gap-3">
                          <span className="capitalize text-muted-foreground">{layer}</span>
                          <span className="font-mono">
                            mean {formatNumber(mean, 3)} · peak {formatNumber(peak, 3)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card className="glass">
              <CardHeader>
                <CardTitle>Profile comparison</CardTitle>
                <CardDescription>
                  Both profiles run on the same grid, start and goal
                </CardDescription>
              </CardHeader>
              <CardContent className="px-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Metric</TableHead>
                      <TableHead className="text-right">Safest</TableHead>
                      <TableHead className="text-right">Shortest</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(
                      [
                        ['Distance (m)', 'distance_m', 0],
                        ['Ascent (m)', 'ascent_m', 0],
                        ['Descent (m)', 'descent_m', 0],
                        ['Minutes', 'estimated_minutes', 0],
                        ['Total cost', 'total_cost', 2],
                        ['Route risk', 'risk_score', 3],
                        ['Max cell risk', 'max_cell_risk', 3],
                        ['Nodes expanded', 'nodes_expanded', 0],
                      ] as const
                    ).map(([label, key, digits]) => (
                      <TableRow key={key}>
                        <TableCell className="text-muted-foreground">{label}</TableCell>
                        <TableCell className="text-right font-mono">
                          {formatNumber(Number(safest?.[key] ?? 0), digits)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {shortest ? formatNumber(Number(shortest[key] ?? 0), digits) : '—'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>

          {plan.hazard_alerts.length > 0 ? (
            <Card className="glass">
              <CardHeader>
                <CardTitle>Hazard alerts raised</CardTitle>
                <CardDescription>
                  Cells on the chosen path exceeded hazard thresholds
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-xs">
                {plan.hazard_alerts.map((a, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Badge variant={a.severity.toLowerCase() as 'high'}>{a.severity}</Badge>
                    <span>{a.title}</span>
                    <span className="text-muted-foreground">({a.action})</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <Card className="glass">
        <CardHeader>
          <CardTitle>Stored routes</CardTitle>
          <CardDescription>Persisted plans with their calculation records</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {history.isLoading ? (
            <LoadingPanel label="Loading routes…" />
          ) : history.error ? (
            <ErrorPanel error={history.error} onRetry={() => history.refetch()} />
          ) : (history.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No saved routes yet"
              description="Plan a route with “Save this route” enabled to store it."
            />
          ) : (
            <Table data-testid="route-history">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Start → Goal</TableHead>
                  <TableHead className="text-right">Profiles</TableHead>
                  <TableHead className="text-right">Safest distance</TableHead>
                  <TableHead className="text-right">Planned</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.data!.items.map((r) => {
                  const safe =
                    r.calculations.find((c) => c.profile.toLowerCase().includes('safe')) ??
                    r.calculations[0];
                  return (
                    <TableRow key={r.id}>
                      <TableCell className="font-medium">{r.name}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        ({r.start_x}, {r.start_y}) → ({r.goal_x}, {r.goal_y})
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {r.calculations.map((c) => c.profile).join(', ') || '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {safe ? `${formatInt(safe.distance_m)} m` : '—'}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {formatDateTime(r.created_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
