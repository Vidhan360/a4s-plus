import { Eye } from 'lucide-react';

import { APP_NAME, TAGLINE, TEAM_NAME } from '@/lib/constants';
import { cn } from '@/lib/utils';

export function Brand({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <div className={cn('flex items-center gap-3', className)}>
      <span className="relative grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary/85 to-accent/85 text-primary-foreground shadow-glow">
        <Eye className="size-[18px]" aria-hidden />
      </span>
      {compact ? null : (
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold tracking-tight">
            {APP_NAME}
            <span className="ml-2 text-[0.65rem] font-medium uppercase tracking-[0.16em] text-muted-foreground">
              {TEAM_NAME}
            </span>
          </span>
          <span className="block truncate text-[0.68rem] text-muted-foreground">{TAGLINE}</span>
        </span>
      )}
    </div>
  );
}
