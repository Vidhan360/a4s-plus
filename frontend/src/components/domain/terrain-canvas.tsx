'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

export type TerrainLayer = 'elevation' | 'avalanche' | 'crevasse' | 'weather' | 'difficulty';

export interface TerrainMarker {
  x: number;
  y: number;
  label: string;
  color: string;
  shape?: 'circle' | 'square' | 'triangle';
}

export interface TerrainCanvasProps {
  width: number;
  height: number;
  elevation: number[][];
  hazard?: number[][];
  blocked?: boolean[][];
  layer: TerrainLayer;
  minElevation: number;
  maxElevation: number;
  path?: [number, number][];
  altPath?: [number, number][];
  markers?: TerrainMarker[];
  hoverCell?: { x: number; y: number } | null;
  onCellClick?: (x: number, y: number) => void;
  onCellHover?: (cell: { x: number; y: number } | null) => void;
  className?: string;
  showGrid?: boolean;
}

/** Linear interpolation between two RGB triples. */
function lerpColor(a: [number, number, number], b: [number, number, number], t: number): string {
  const clamped = Math.min(1, Math.max(0, t));
  const channel = (index: 0 | 1 | 2) => Math.round(a[index] + (b[index] - a[index]) * clamped);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

/** Hypsometric ramp: valley green → rock brown → snow white. */
function elevationColor(t: number): string {
  if (t < 0.35) return lerpColor([18, 46, 42], [46, 74, 48], t / 0.35);
  if (t < 0.62) return lerpColor([46, 74, 48], [104, 88, 66], (t - 0.35) / 0.27);
  if (t < 0.82) return lerpColor([104, 88, 66], [156, 152, 148], (t - 0.62) / 0.2);
  return lerpColor([156, 152, 148], [244, 250, 255], (t - 0.82) / 0.18);
}

/** Hazard ramp: transparent-ish teal → amber → red. */
function hazardColor(t: number): string {
  if (t < 0.5) return lerpColor([16, 58, 70], [232, 168, 30], t / 0.5);
  return lerpColor([232, 168, 30], [214, 44, 44], (t - 0.5) / 0.5);
}

/**
 * Canvas terrain renderer.
 *
 * A 64×64 grid with hazard overlays, hillshading and two route polylines is
 * far too much for one DOM node per cell, so the map is drawn on a canvas at
 * device pixel ratio and only re-drawn when its inputs change.
 */
export function TerrainCanvas({
  width,
  height,
  elevation,
  hazard,
  blocked,
  layer,
  minElevation,
  maxElevation,
  path,
  altPath,
  markers = [],
  hoverCell,
  onCellClick,
  onCellHover,
  className,
  showGrid = false,
}: TerrainCanvasProps) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null);
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const [pixelSize, setPixelSize] = React.useState(560);

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setPixelSize(Math.max(240, Math.floor(entry.contentRect.width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const dpr = typeof window === 'undefined' ? 1 : Math.min(window.devicePixelRatio || 1, 2);
    const cssWidth = pixelSize;
    const cssHeight = Math.round((pixelSize * height) / width);
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, cssWidth, cssHeight);

    const cellW = cssWidth / width;
    const cellH = cssHeight / height;
    const span = Math.max(1e-6, maxElevation - minElevation);

    for (let y = 0; y < height; y += 1) {
      const elevRow = elevation[y] ?? [];
      const hazardRow = hazard?.[y];
      for (let x = 0; x < width; x += 1) {
        const elev = elevRow[x] ?? minElevation;
        const normalised = (elev - minElevation) / span;

        if (layer === 'elevation' || !hazardRow) {
          context.fillStyle = elevationColor(normalised);
        } else {
          // Hazard layers keep the terrain visible underneath so the operator
          // can still see *where* the hazard is.
          context.fillStyle = elevationColor(normalised);
          context.fillRect(x * cellW, y * cellH, cellW + 0.6, cellH + 0.6);
          const value = Math.min(1, Math.max(0, hazardRow[x] ?? 0));
          context.globalAlpha = 0.18 + 0.66 * value;
          context.fillStyle = hazardColor(value);
        }

        context.fillRect(x * cellW, y * cellH, cellW + 0.6, cellH + 0.6);
        context.globalAlpha = 1;

        // Simple hillshade from the west-neighbour slope.
        const west = elevRow[x - 1];
        if (west !== undefined) {
          const slope = (elev - west) / span;
          if (Math.abs(slope) > 0.004) {
            context.fillStyle =
              slope > 0 ? 'rgba(255,255,255,0.085)' : 'rgba(0,0,0,0.135)';
            context.fillRect(x * cellW, y * cellH, cellW + 0.6, cellH + 0.6);
          }
        }

        if (blocked?.[y]?.[x]) {
          context.strokeStyle = 'rgba(255,64,64,0.55)';
          context.lineWidth = 0.85;
          context.beginPath();
          context.moveTo(x * cellW, y * cellH);
          context.lineTo((x + 1) * cellW, (y + 1) * cellH);
          context.stroke();
        }
      }
    }

    if (showGrid && cellW > 6) {
      context.strokeStyle = 'rgba(255,255,255,0.05)';
      context.lineWidth = 0.5;
      for (let x = 0; x <= width; x += 8) {
        context.beginPath();
        context.moveTo(x * cellW, 0);
        context.lineTo(x * cellW, cssHeight);
        context.stroke();
      }
      for (let y = 0; y <= height; y += 8) {
        context.beginPath();
        context.moveTo(0, y * cellH);
        context.lineTo(cssWidth, y * cellH);
        context.stroke();
      }
    }

    const drawPath = (points: [number, number][], stroke: string, dash: number[]) => {
      if (points.length < 2) return;
      context.save();
      context.setLineDash(dash);
      context.strokeStyle = stroke;
      context.lineWidth = Math.max(1.8, cellW * 0.34);
      context.lineJoin = 'round';
      context.lineCap = 'round';
      context.beginPath();
      points.forEach(([px, py], index) => {
        const cx = (px + 0.5) * cellW;
        const cy = (py + 0.5) * cellH;
        if (index === 0) context.moveTo(cx, cy);
        else context.lineTo(cx, cy);
      });
      context.stroke();
      context.restore();
    };

    if (altPath) drawPath(altPath, 'rgba(255,255,255,0.55)', [5, 4]);
    if (path) drawPath(path, 'rgba(56, 232, 255, 0.95)', []);

    for (const marker of markers) {
      const cx = (marker.x + 0.5) * cellW;
      const cy = (marker.y + 0.5) * cellH;
      const r = Math.max(3.4, cellW * 0.5);
      context.save();
      context.fillStyle = marker.color;
      context.strokeStyle = 'rgba(6,10,18,0.85)';
      context.lineWidth = 1.4;
      context.beginPath();
      if (marker.shape === 'square') {
        context.rect(cx - r, cy - r, r * 2, r * 2);
      } else if (marker.shape === 'triangle') {
        context.moveTo(cx, cy - r * 1.2);
        context.lineTo(cx + r, cy + r * 0.9);
        context.lineTo(cx - r, cy + r * 0.9);
        context.closePath();
      } else {
        context.arc(cx, cy, r, 0, Math.PI * 2);
      }
      context.fill();
      context.stroke();
      context.restore();
    }

    if (hoverCell) {
      context.strokeStyle = 'rgba(255,255,255,0.85)';
      context.lineWidth = 1.2;
      context.strokeRect(hoverCell.x * cellW, hoverCell.y * cellH, cellW, cellH);
    }
  }, [
    width,
    height,
    elevation,
    hazard,
    blocked,
    layer,
    minElevation,
    maxElevation,
    path,
    altPath,
    markers,
    hoverCell,
    pixelSize,
    showGrid,
  ]);

  const cellFromEvent = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor(((event.clientX - rect.left) / rect.width) * width);
    const y = Math.floor(((event.clientY - rect.top) / rect.height) * height);
    if (x < 0 || y < 0 || x >= width || y >= height) return null;
    return { x, y };
  };

  return (
    <div ref={containerRef} className={cn('w-full', className)}>
      <canvas
        ref={canvasRef}
        data-testid="terrain-canvas"
        className={cn(
          'block rounded-lg border border-white/[0.08]',
          onCellClick ? 'cursor-crosshair' : undefined,
        )}
        onClick={(event) => {
          const cell = cellFromEvent(event);
          if (cell && onCellClick) onCellClick(cell.x, cell.y);
        }}
        onMouseMove={(event) => onCellHover?.(cellFromEvent(event))}
        onMouseLeave={() => onCellHover?.(null)}
        role="img"
        aria-label={`Synthetic terrain map, ${width} by ${height} cells, ${layer} layer`}
      />
    </div>
  );
}
