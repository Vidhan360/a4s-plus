'use client';

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';

import { ChartFrame, Swatch, tooltipStyle } from '@/components/charts/chart-frame';
import { EmptyState } from '@/components/ui/states';
import { RISK_CATEGORIES, RISK_COLORS, type RiskCategory } from '@/lib/constants';

export function RiskDistributionChart({
  distribution,
  height = 200,
}: {
  distribution: Record<string, number>;
  height?: number;
}) {
  const data = RISK_CATEGORIES.map((category) => ({
    name: category,
    value: distribution[category] ?? 0,
  })).filter((entry) => entry.value > 0);

  const total = data.reduce((sum, entry) => sum + entry.value, 0);

  if (total === 0) {
    return (
      <EmptyState
        title="No risk assessments yet"
        description="Risk categories appear once telemetry has been scored."
      />
    );
  }

  return (
    <div className="space-y-3">
      <ChartFrame height={height}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius="58%"
              outerRadius="86%"
              paddingAngle={3}
              stroke="none"
            >
              {data.map((entry) => (
                <Cell key={entry.name} fill={RISK_COLORS[entry.name as RiskCategory]} />
              ))}
            </Pie>
            <Tooltip
              {...tooltipStyle}
              formatter={(value: number, name) => [
                `${value} (${((value / total) * 100).toFixed(0)}%)`,
                String(name),
              ]}
            />
          </PieChart>
        </ResponsiveContainer>
      </ChartFrame>
      <div className="flex flex-wrap justify-center gap-3">
        {data.map((entry) => (
          <Swatch
            key={entry.name}
            color={RISK_COLORS[entry.name as RiskCategory]}
            label={`${entry.name} · ${entry.value}`}
          />
        ))}
      </div>
    </div>
  );
}
