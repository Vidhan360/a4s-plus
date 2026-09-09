'use client';

import { AlertTriangle, Inbox, Loader2, RefreshCw, ShieldOff } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError, errorMessage } from '@/lib/api-error';
import { cn } from '@/lib/utils';

/** Inline spinner for buttons and small regions. */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-4 animate-spin text-muted-foreground', className)} aria-hidden />;
}

export function LoadingPanel({ label = 'Loading…', rows = 4 }: { label?: string; rows?: number }) {
  return (
    <div className="space-y-3 p-1" role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  );
}

export function LoadingStat() {
  return (
    <div className="space-y-2" role="status" aria-busy="true">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-8 w-20" />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: {
  title: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-white/[0.09] px-6 py-12 text-center',
        className,
      )}
    >
      <div className="rounded-full bg-white/[0.04] p-3">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description ? (
          <p className="mx-auto max-w-md text-xs leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

/**
 * Error surface used by every data panel.
 *
 * A 403 is shown as a permissions message rather than a failure, because the
 * RBAC model deliberately hides capabilities from lower-privileged roles and
 * that is not an error the user can fix by retrying.
 */
export function ErrorPanel({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const forbidden = error instanceof ApiError && error.isForbidden;
  const requestId = error instanceof ApiError ? error.requestId : null;

  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center',
        forbidden ? 'border-white/[0.09]' : 'border-destructive/30 bg-destructive/[0.04]',
        className,
      )}
      role="alert"
    >
      <div className={cn('rounded-full p-3', forbidden ? 'bg-white/[0.04]' : 'bg-destructive/10')}>
        {forbidden ? (
          <ShieldOff className="size-5 text-muted-foreground" />
        ) : (
          <AlertTriangle className="size-5 text-destructive" />
        )}
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {forbidden ? 'Your role does not include this view' : 'Could not load this panel'}
        </p>
        <p className="mx-auto max-w-md text-xs leading-relaxed text-muted-foreground">
          {errorMessage(error)}
        </p>
        {requestId ? (
          <p className="font-mono text-[0.65rem] text-muted-foreground/70">
            request {requestId}
          </p>
        ) : null}
      </div>
      {onRetry && !forbidden ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RefreshCw />
          Retry
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Standard query-state wrapper. Keeps loading/empty/error handling identical
 * on every screen instead of re-implementing it per panel.
 */
export function QueryBoundary<T>({
  isLoading,
  error,
  data,
  onRetry,
  loading,
  empty,
  isEmpty,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  data: T | undefined;
  onRetry?: () => void;
  loading?: React.ReactNode;
  empty?: React.ReactNode;
  isEmpty?: (data: T) => boolean;
  children: (data: T) => React.ReactNode;
}) {
  if (isLoading) return <>{loading ?? <LoadingPanel />}</>;
  if (error) return <ErrorPanel error={error} onRetry={onRetry} />;
  if (data === undefined) return <>{empty ?? <EmptyState title="No data available" />}</>;
  if (isEmpty?.(data)) return <>{empty ?? <EmptyState title="Nothing to show yet" />}</>;
  return <>{children(data)}</>;
}
