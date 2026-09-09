import * as React from 'react';

import { Card } from '@/components/ui/card';
import { LoadingStat } from '@/components/ui/states';
import { cn } from '@/lib/utils';

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent = 'primary',
  loading = false,
  className,
  testId,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  accent?: 'primary' | 'low' | 'moderate' | 'high' | 'critical' | 'muted';
  loading?: boolean;
  className?: string;
  /** Optional hook for end-to-end assertions on a specific metric. */
  testId?: string;
}) {
  const accents: Record<string, string> = {
    primary: 'text-primary',
    low: 'text-risk-low',
    moderate: 'text-risk-moderate',
    high: 'text-risk-high',
    critical: 'text-risk-critical',
    muted: 'text-muted-foreground',
  };

  return (
    <Card className={cn('relative overflow-hidden p-5', className)}>
      <div className="pointer-events-none absolute inset-x-0 -top-16 h-24 bg-radial-fade opacity-60" />
      {loading ? (
        <LoadingStat />
      ) : (
        <div className="relative flex items-start justify-between gap-3">
          <div className="space-y-1.5">
            <p className="label-muted">{label}</p>
            <p className={cn('stat-value', accents[accent])} data-testid={testId}>
              {value}
            </p>
            {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
          </div>
          {Icon ? (
            <div className="rounded-lg bg-white/[0.05] p-2">
              <Icon className={cn('size-4', accents[accent])} />
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
