'use client';

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { axisProps, ChartFrame, gridProps, tooltipStyle } from '@/components/charts/chart-frame';
import { EmptyState } from '@/components/ui/states';
import type { ModelComparisonEntry } from '@/lib/types';

const LABELS: Record<string, string> = {
  rule_baseline: 'Rule baseline',
  lstm: 'LSTM',
  gradient_boosting: 'Gradient boosting',
};

export function ModelComparisonChart({
  models,
  height = 260,
}: {
  models: ModelComparisonEntry[];
  height?: number;
}) {
  const data = models.map((entry) => ({
    name: LABELS[entry.model] ?? entry.model,
    Accuracy: Number((entry.accuracy * 100).toFixed(2)),
    'Macro F1': Number((entry.macro_f1 * 100).toFixed(2)),
    'Elevated-risk F1':
      entry.elevated_f1 === null || entry.elevated_f1 === undefined
        ? null
        : Number((entry.elevated_f1 * 100).toFixed(2)),
  }));

  if (data.length === 0) {
    return (
      <EmptyState
        title="No measured metrics available"
        description="Run the training pipeline to produce a comparison artefact."
      />
    );
  }

  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid {...gridProps} />
          <XAxis dataKey="name" {...axisProps} />
          <YAxis domain={[0, 100]} unit="%" {...axisProps} />
          <Tooltip
            {...tooltipStyle}
            formatter={(value, name) => [
              typeof value === 'number' ? `${value.toFixed(2)}%` : 'not applicable',
              String(name),
            ]}
            cursor={{ fill: 'hsl(0 0% 100% / 0.04)' }}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
          <Bar dataKey="Accuracy" fill="hsl(190 95% 52%)" radius={[4, 4, 0, 0]} barSize={22} />
          <Bar dataKey="Macro F1" fill="hsl(262 83% 70%)" radius={[4, 4, 0, 0]} barSize={22} />
          <Bar
            dataKey="Elevated-risk F1"
            fill="hsl(152 68% 50%)"
            radius={[4, 4, 0, 0]}
            barSize={22}
          />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
