'use client';

import { useQuery } from '@tanstack/react-query';
import { Layers, Mountain, TriangleAlert } from 'lucide-react';
import * as React from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { TerrainCanvas, type TerrainLayer } from '@/components/domain/terrain-canvas';
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
import { ErrorPanel, LoadingPanel } from '@/components/ui/states';
import { api } from '@/lib/api-client';
import { formatInt, formatNumber, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { TerrainGrid, TerrainMap } from '@/lib/types';

interface TerrainCell {
  x: number;
  y: number;
  elevation_m: number;
  terrain_type: string;
  difficulty: number;
  avalanche_risk: number;
  crevasse_risk: number;
  weather_risk: number;
  blocked: boolean;
  is_synthetic: boolean;
}

interface LegendResponse {
  types: { code: string; label: string; description: string; traversable: boolean }[];
  hazards: { code: string; label: string; description: string }[];
  notice: string;
}

const LAYERS: { value: TerrainLayer; label: string; hint: string }[] = [
  { value: 'elevation', label: 'Elevation', hint: 'Hypsometric relief with hillshading' },
  { value: 'avalanche', label: 'Avalanche risk', hint: 'Slope- and aspect-derived release potential' },
  { value: 'crevasse', label: 'Crevasse risk', hint: 'Glacier and icefall cell probability' },
  { value: 'weather', label: 'Weather exposure', hint: 'Wind and visibility penalty per cell' },
  { value: 'difficulty', label: 'Traverse difficulty', hint: 'Composite movement cost multiplier' },
];

/** Terrain intelligence: procedurally generated grid, hazard layers, cell inspector. */
export default function TerrainPage() {
  const [layer, setLayer] = React.useState<TerrainLayer>('elevation');
  const [mapId, setMapId] = React.useState<string | undefined>(undefined);
  const [hover, setHover] = React.useState<{ x: number; y: number } | null>(null);
  const [selected, setSelected] = React.useState<{ x: number; y: number } | null>(null);

  const maps = useQuery<TerrainMap[]>({
    queryKey: qk.terrainMaps,
    queryFn: () => api.get<TerrainMap[]>('/terrain/maps'),
  });

  const activeMapId = mapId ?? maps.data?.[0]?.id;

  const grid = useQuery<TerrainGrid>({
    queryKey: qk.terrainGrid(activeMapId),
    queryFn: () =>
      api.get<TerrainGrid>('/terrain/grid', activeMapId ? { map_id: activeMapId } : undefined),
    enabled: maps.isSuccess,
    staleTime: 10 * 60 * 1000,
  });

  const legend = useQuery<LegendResponse>({
    queryKey: qk.terrainLegend,
    queryFn: () => api.get<LegendResponse>('/terrain/legend'),
    staleTime: 60 * 60 * 1000,
  });

  const cell = useQuery<TerrainCell>({
    queryKey: ['terrain', 'cell', activeMapId, selected?.x, selected?.y],
    queryFn: () =>
      api.get<TerrainCell>('/terrain/cell', {
        x: selected!.x,
        y: selected!.y,
        ...(activeMapId ? { map_id: activeMapId } : {}),
      }),
    enabled: selected !== null,
  });

  const hazardLayer = React.useMemo(() => {
    if (!grid.data || layer === 'elevation') return undefined;
    return grid.data[layer];
  }, [grid.data, layer]);

  const stats = React.useMemo(() => {
    if (!grid.data) return null;
    const flat = grid.data.elevation.flat();
    const blockedCount = grid.data.blocked.flat().filter(Boolean).length;
    const avalancheHigh = grid.data.avalanche.flat().filter((v) => v >= 0.66).length;
    const typeCounts = new Map<string, number>();
    for (const row of grid.data.terrain_type) {
      for (const code of row) typeCounts.set(code, (typeCounts.get(code) ?? 0) + 1);
    }
    return {
      cells: flat.length,
      blockedCount,
      avalancheHigh,
      types: [...typeCounts.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [grid.data]);

  const hoverInfo = React.useMemo(() => {
    if (!grid.data || !hover) return null;
    const { x, y } = hover;
    return {
      x,
      y,
      elevation: grid.data.elevation[y]?.[x],
      type: grid.data.terrain_type[y]?.[x],
      avalanche: grid.data.avalanche[y]?.[x],
      crevasse: grid.data.crevasse[y]?.[x],
      weather: grid.data.weather[y]?.[x],
      difficulty: grid.data.difficulty[y]?.[x],
      blocked: grid.data.blocked[y]?.[x],
    };
  }, [grid.data, hover]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Terrain intelligence"
        description="Procedurally generated high-altitude terrain with per-cell hazard layers. This is synthetic terrain produced by a seeded generator — it is not DEM, satellite or survey data, and it must not be used for real navigation."
        actions={
          <>
            {maps.data && maps.data.length > 1 ? (
              <Select value={activeMapId} onValueChange={setMapId}>
                <SelectTrigger className="w-52" aria-label="Terrain map">
                  <SelectValue placeholder="Map" />
                </SelectTrigger>
                <SelectContent>
                  {maps.data.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : null}
            <Select value={layer} onValueChange={(v) => setLayer(v as TerrainLayer)}>
              <SelectTrigger className="w-52" data-testid="terrain-layer" aria-label="Hazard layer">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LAYERS.map((l) => (
                  <SelectItem key={l.value} value={l.value}>
                    {l.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </>
        }
      />

      <Alert>
        <TriangleAlert />
        <AlertTitle>Synthetic terrain</AlertTitle>
        <AlertDescription>
          {legend.data?.notice ??
            'Elevation and hazard values are generated from a deterministic noise model for demonstration purposes.'}
        </AlertDescription>
      </Alert>

      {maps.isLoading || grid.isLoading ? (
        <LoadingPanel label="Generating terrain grid…" rows={6} />
      ) : grid.error ? (
        <ErrorPanel error={grid.error} onRetry={() => grid.refetch()} />
      ) : grid.data && stats ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Grid size"
              value={`${grid.data.map.width} × ${grid.data.map.height}`}
              hint={`${formatInt(stats.cells)} cells at ${formatInt(grid.data.map.cell_size_m)} m`}
              icon={Layers}
            />
            <StatCard
              label="Elevation band"
              value={`${formatInt(grid.data.map.min_elevation_m)}–${formatInt(grid.data.map.max_elevation_m)} m`}
              hint="Generator output range"
              icon={Mountain}
            />
            <StatCard
              label="Impassable cells"
              value={formatInt(stats.blockedCount)}
              hint={`${formatNumber((stats.blockedCount / stats.cells) * 100, 1)}% of the grid`}
              accent="high"
            />
            <StatCard
              label="High avalanche cells"
              value={formatInt(stats.avalancheHigh)}
              hint="Risk ≥ 0.66"
              accent="critical"
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="glass">
              <CardHeader>
                <CardTitle>{LAYERS.find((l) => l.value === layer)?.label}</CardTitle>
                <CardDescription>
                  {LAYERS.find((l) => l.value === layer)?.hint} · click a cell to inspect it
                </CardDescription>
              </CardHeader>
              <CardContent>
                <TerrainCanvas
                  width={grid.data.map.width}
                  height={grid.data.map.height}
                  elevation={grid.data.elevation}
                  hazard={hazardLayer}
                  blocked={grid.data.blocked}
                  layer={layer}
                  minElevation={grid.data.map.min_elevation_m}
                  maxElevation={grid.data.map.max_elevation_m}
                  hoverCell={hover}
                  onCellHover={setHover}
                  onCellClick={(x, y) => setSelected({ x, y })}
                  markers={selected ? [{ ...selected, label: 'Inspect', color: '#38bdf8' }] : []}
                />
                <div className="mt-3 flex items-center justify-between gap-3 text-[0.7rem] text-muted-foreground">
                  <span>
                    {hoverInfo
                      ? `(${hoverInfo.x}, ${hoverInfo.y}) · ${formatInt(hoverInfo.elevation ?? 0)} m · ${titleCase(hoverInfo.type ?? '')}${hoverInfo.blocked ? ' · impassable' : ''}`
                      : 'Hover the map for cell readouts'}
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="h-1.5 w-16 rounded-full bg-gradient-to-r from-[#122e2a] via-[#685842] to-white" />
                    low → high
                  </span>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card className="glass">
                <CardHeader>
                  <CardTitle>Cell inspector</CardTitle>
                  <CardDescription>
                    {selected ? `Grid (${selected.x}, ${selected.y})` : 'Select a cell on the map'}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {!selected ? (
                    <p className="text-xs text-muted-foreground">
                      Clicking a cell queries the backend for its authoritative values, so the
                      inspector shows server truth rather than the client-side render.
                    </p>
                  ) : cell.isLoading ? (
                    <LoadingPanel label="Reading cell…" rows={3} />
                  ) : cell.error ? (
                    <ErrorPanel error={cell.error} onRetry={() => cell.refetch()} />
                  ) : cell.data ? (
                    <dl className="space-y-2 text-xs" data-testid="terrain-cell">
                      {[
                        ['Terrain type', titleCase(cell.data.terrain_type)],
                        ['Elevation', `${formatInt(cell.data.elevation_m)} m`],
                        ['Traverse difficulty', formatNumber(cell.data.difficulty, 2)],
                        ['Avalanche risk', formatNumber(cell.data.avalanche_risk, 2)],
                        ['Crevasse risk', formatNumber(cell.data.crevasse_risk, 2)],
                        ['Weather exposure', formatNumber(cell.data.weather_risk, 2)],
                      ].map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between gap-3">
                          <dt className="text-muted-foreground">{k}</dt>
                          <dd className="font-mono">{v}</dd>
                        </div>
                      ))}
                      <div className="flex items-center justify-between gap-3 pt-1">
                        <dt className="text-muted-foreground">Passable</dt>
                        <dd>
                          <Badge variant={cell.data.blocked ? 'critical' : 'low'}>
                            {cell.data.blocked ? 'Impassable' : 'Passable'}
                          </Badge>
                        </dd>
                      </div>
                    </dl>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="glass">
                <CardHeader>
                  <CardTitle>Terrain composition</CardTitle>
                  <CardDescription>Cell counts by generated type</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2">
                  {stats.types.map(([code, count]) => {
                    const meta = legend.data?.types.find((t) => t.code === code);
                    const pct = (count / stats.cells) * 100;
                    return (
                      <div key={code} className="space-y-1">
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <span title={meta?.description}>{meta?.label ?? titleCase(code)}</span>
                          <span className="font-mono text-muted-foreground">
                            {formatNumber(pct, 1)}%
                          </span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                          <div
                            className="h-full rounded-full bg-primary/70"
                            style={{ width: `${Math.max(pct, 1)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </CardContent>
              </Card>

              {legend.data ? (
                <Card className="glass">
                  <CardHeader>
                    <CardTitle>Hazard layers</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-xs">
                    {legend.data.hazards.map((h) => (
                      <div key={h.code}>
                        <p className="font-medium">{h.label}</p>
                        <p className="text-muted-foreground">{h.description}</p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
