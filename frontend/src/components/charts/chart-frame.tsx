'use client';

import * as React from 'react';

import { cn } from '@/lib/utils';

/** Shared tooltip styling so every Recharts tooltip looks the same. */
export const tooltipStyle = {
  contentStyle: {
    background: 'hsl(222 44% 7% / 0.95)',
    border: '1px solid hsl(0 0% 100% / 0.1)',
    borderRadius: '10px',
    backdropFilter: 'blur(16px)',
    fontSize: '11px',
    padding: '8px 10px',
  },
  labelStyle: { color: 'hsl(215 20% 66%)', fontSize: '10px', marginBottom: 4 },
  itemStyle: { fontSize: '11px', padding: 0 },
} as const;

export const axisProps = {
  stroke: 'hsl(215 20% 66% / 0.45)',
  tick: { fill: 'hsl(215 20% 66%)', fontSize: 10 },
  tickLine: false,
} as const;

export const gridProps = {
  stroke: 'hsl(217 28% 20% / 0.7)',
  strokeDasharray: '3 3',
  vertical: false,
} as const;

export function ChartFrame({
  height = 260,
  children,
  className,
}: {
  height?: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('w-full', className)} style={{ height }}>
      {children}
    </div>
  );
}

/** Legend swatch reused outside Recharts (e.g. for the canvas map). */
export function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[0.68rem] text-muted-foreground">
      <span className="size-2 rounded-sm" style={{ background: color }} />
      {label}
    </span>
  );
}
