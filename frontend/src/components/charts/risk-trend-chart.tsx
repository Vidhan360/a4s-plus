'use client';

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { axisProps, ChartFrame, gridProps, tooltipStyle } from '@/components/charts/chart-frame';
import { EmptyState } from '@/components/ui/states';
import { formatTime } from '@/lib/format';

export interface RiskTrendPoint {
  bucket: string;
  mean_risk: number;
  max_risk?: number;
  samples: number;
}

export function RiskTrendChart({ data, height = 240 }: { data: RiskTrendPoint[]; height?: number }) {
  if (data.length === 0) {
    return (
      <EmptyState
        title="No risk history in this window"
        description="Start the simulation, or widen the time window, to populate the trend."
      />
    );
  }

  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="riskTrendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(190 95% 52%)" stopOpacity={0.45} />
              <stop offset="100%" stopColor="hsl(190 95% 52%)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="bucket" tickFormatter={formatTime} {...axisProps} />
          <YAxis domain={[0, 100]} {...axisProps} />
          <Tooltip
            {...tooltipStyle}
            labelFormatter={(value) => formatTime(String(value))}
            formatter={(value) => [
              typeof value === 'number' ? value.toFixed(1) : String(value),
              'Mean risk',
            ]}
          />
          <Area
            type="monotone"
            dataKey="mean_risk"
            stroke="hsl(190 95% 52%)"
            strokeWidth={2}
            fill="url(#riskTrendFill)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
