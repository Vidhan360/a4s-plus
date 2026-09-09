'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { axisProps, ChartFrame, gridProps, tooltipStyle } from '@/components/charts/chart-frame';
import { EmptyState } from '@/components/ui/states';
import { featureLabel } from '@/lib/format';

export interface FactorBar {
  feature: string;
  value: number;
}

/** Horizontal contribution chart used by the risk and explainability panels. */
export function FactorBarChart({
  data,
  height = 220,
  colorFor,
  valueLabel = 'Contribution',
}: {
  data: FactorBar[];
  height?: number;
  colorFor?: (entry: FactorBar) => string;
  valueLabel?: string;
}) {
  if (data.length === 0) {
    return <EmptyState title="No contributing factors" description="Nothing is driving the score." />;
  }

  const rows = data.map((entry) => ({ ...entry, label: featureLabel(entry.feature) }));

  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 12 }}>
          <CartesianGrid {...gridProps} vertical horizontal={false} />
          <XAxis type="number" {...axisProps} />
          <YAxis type="category" dataKey="label" width={124} {...axisProps} />
          <Tooltip
            {...tooltipStyle}
            formatter={(value: number) => [value.toFixed(3), valueLabel]}
            cursor={{ fill: 'hsl(0 0% 100% / 0.04)' }}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={13}>
            {rows.map((entry) => (
              <Cell
                key={entry.feature}
                fill={colorFor ? colorFor(entry) : 'hsl(190 95% 52%)'}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
