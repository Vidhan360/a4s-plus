import { type VariantProps, cva } from 'class-variance-authority';
import * as React from 'react';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.68rem] font-semibold uppercase tracking-wider transition-colors',
  {
    variants: {
      variant: {
        default: 'border-primary/30 bg-primary/12 text-primary',
        secondary: 'border-white/10 bg-white/[0.06] text-foreground/80',
        outline: 'border-border text-muted-foreground',
        destructive: 'border-destructive/40 bg-destructive/15 text-destructive',
        low: 'border-risk-low/40 bg-risk-low/15 text-risk-low',
        moderate: 'border-risk-moderate/40 bg-risk-moderate/15 text-risk-moderate',
        high: 'border-risk-high/40 bg-risk-high/15 text-risk-high',
        critical: 'border-risk-critical/45 bg-risk-critical/15 text-risk-critical',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
