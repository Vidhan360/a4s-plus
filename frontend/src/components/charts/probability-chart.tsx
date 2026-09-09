'use client';

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { axisProps, ChartFrame, tooltipStyle } from '@/components/charts/chart-frame';
import { RISK_CATEGORIES, RISK_COLORS, type RiskCategory } from '@/lib/constants';

/** Class-probability distribution from a prediction. */
export function ProbabilityChart({
  probabilities,
  height = 160,
}: {
  probabilities: Record<string, number>;
  height?: number;
}) {
  const data = RISK_CATEGORIES.map((category) => ({
    name: category,
    value: Number(((probabilities[category] ?? 0) * 100).toFixed(2)),
  }));

  return (
    <ChartFrame height={height}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
          <XAxis dataKey="name" {...axisProps} />
          <YAxis domain={[0, 100]} unit="%" {...axisProps} />
          <Tooltip
            {...tooltipStyle}
            formatter={(value: number) => [`${value.toFixed(2)}%`, 'Probability']}
            cursor={{ fill: 'hsl(0 0% 100% / 0.04)' }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={34}>
            {data.map((entry) => (
              <Cell key={entry.name} fill={RISK_COLORS[entry.name as RiskCategory]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
