import { Badge, type BadgeProps } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

const VARIANTS: Record<string, BadgeProps['variant']> = {
  LOW: 'low',
  MODERATE: 'moderate',
  HIGH: 'high',
  CRITICAL: 'critical',
  INFO: 'secondary',
  WARNING: 'moderate',
  EMERGENCY: 'critical',
};

export function RiskBadge({
  category,
  score,
  className,
  pulse = false,
}: {
  category: string | null | undefined;
  score?: number | null;
  className?: string;
  pulse?: boolean;
}) {
  if (!category) {
    return (
      <Badge variant="outline" className={className}>
        No data
      </Badge>
    );
  }
  const variant = VARIANTS[category.toUpperCase()] ?? 'secondary';
  const isCritical = category.toUpperCase() === 'CRITICAL';
  return (
    <Badge
      variant={variant}
      className={cn(pulse && isCritical && 'animate-pulse-ring', className)}
      title={score === null || score === undefined ? undefined : `Risk score ${score.toFixed(1)}/100`}
    >
      {category}
      {score === null || score === undefined ? null : (
        <span className="font-mono tabular-nums opacity-80">{score.toFixed(0)}</span>
      )}
    </Badge>
  );
}
