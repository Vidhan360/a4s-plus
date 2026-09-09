'use client';

import * as React from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { axisProps, ChartFrame, gridProps, tooltipStyle } from '@/components/charts/chart-frame';
import { EmptyState } from '@/components/ui/states';
import { featureLabel, formatTime, unitFor } from '@/lib/format';
import type { VitalReading } from '@/lib/types';

const SERIES_COLORS = [
  'hsl(190 95% 52%)',
  'hsl(262 83% 70%)',
  'hsl(152 68% 50%)',
  'hsl(42 96% 56%)',
  'hsl(0 84% 62%)',
];

/**
 * Multi-series vitals chart.
 *
 * Readings arrive newest-first from the API; the chart reverses them so time
 * runs left to right, which is what every reviewer expects.
 */
export function VitalsChart({
  readings,
  keys,
  reference,
  height = 260,
}: {
  readings: VitalReading[];
  keys: (keyof VitalReading)[];
  reference?: { value: number; label: string };
  height?: number;
}) {
  const data = React.useMemo(
    () =>
      [...readings].reverse().map((reading) => ({
        recorded_at: reading.recorded_at,
        ...Object.fromEntries(keys.map((key) => [key, reading[key]])),
      })),
    [readings, keys],
  );

  if (data.length === 0) {
    return (
      <EmptyState
        title="No readings for this window"
        description="Vitals appear as the simulation engine emits telemetry."
      />
    );
  }

  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="recorded_at" tickFormatter={formatTime} {...axisProps} />
          <YAxis {...axisProps} />
          <Tooltip
            {...tooltipStyle}
            labelFormatter={(value) => formatTime(String(value))}
            formatter={(value: number, name) => [
              `${value.toFixed(1)} ${unitFor(String(name))}`.trim(),
              featureLabel(String(name)),
            ]}
          />
          {reference ? (
            <ReferenceLine
              y={reference.value}
              stroke="hsl(0 84% 60% / 0.55)"
              strokeDasharray="4 4"
              label={{
                value: reference.label,
                fill: 'hsl(0 84% 68%)',
                fontSize: 10,
                position: 'insideTopRight',
              }}
            />
          ) : null}
          {keys.map((key, index) => (
            <Line
              key={String(key)}
              type="monotone"
              dataKey={String(key)}
              stroke={SERIES_COLORS[index % SERIES_COLORS.length]}
              strokeWidth={1.9}
              dot={false}
              activeDot={{ r: 3 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
