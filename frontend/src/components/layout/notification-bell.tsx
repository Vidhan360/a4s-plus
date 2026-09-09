'use client';

import { useQuery } from '@tanstack/react-query';
import { Bell, BellRing } from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';

import { RiskBadge } from '@/components/domain/risk-badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/states';
import { useLiveStream } from '@/hooks/use-live-stream';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { PERM } from '@/lib/constants';
import { formatRelative } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Alert, Paged } from '@/lib/types';
import { cn } from '@/lib/utils';

export function NotificationBell() {
  const { can } = useSession();
  const mayRead = can(PERM.alertRead);
  const { events } = useLiveStream();

  const { data } = useQuery({
    queryKey: qk.alerts({ bell: true }),
    queryFn: () =>
      api.get<Paged<Alert>>('/alerts', { status: 'OPEN', limit: 8 }),
    enabled: mayRead,
    refetchInterval: 20_000,
  });

  const alerts = data?.items ?? [];
  const critical = alerts.filter((alert) => alert.severity === 'CRITICAL' || alert.severity === 'EMERGENCY');
  const unseen = events.filter((event) => event.topic === 'alerts').length;

  if (!mayRead) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          className="relative"
          aria-label={`Alerts (${alerts.length} open)`}
          data-testid="notification-bell"
        >
          {critical.length > 0 ? (
            <BellRing className="size-4 text-risk-critical" />
          ) : (
            <Bell className="size-4" />
          )}
          {alerts.length > 0 ? (
            <span
              className={cn(
                'absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full px-1 text-[0.6rem] font-bold',
                critical.length > 0
                  ? 'bg-risk-critical text-white'
                  : 'bg-primary text-primary-foreground',
              )}
            >
              {alerts.length}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[360px] p-0">
        <DropdownMenuLabel className="flex items-center justify-between px-3 py-2.5 text-xs">
          <span>Open alerts</span>
          <span className="font-normal text-muted-foreground">
            {unseen > 0 ? `${unseen} live update${unseen === 1 ? '' : 's'}` : 'Simulated data'}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="mx-0 my-0" />
        {alerts.length === 0 ? (
          <div className="p-3">
            <EmptyState
              title="No open alerts"
              description="The alert engine has nothing outstanding. Start the simulation to generate activity."
              className="border-0 py-6"
            />
          </div>
        ) : (
          <div className="max-h-[380px] overflow-y-auto py-1">
            {alerts.map((alert) => (
              <DropdownMenuItem key={alert.id} asChild className="px-3 py-2.5">
                <Link href="/alerts" className="flex w-full flex-col items-start gap-1.5">
                  <span className="flex w-full items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium">{alert.title}</span>
                    <RiskBadge category={alert.severity} />
                  </span>
                  <span className="line-clamp-2 text-[0.7rem] leading-relaxed text-muted-foreground">
                    {alert.reason}
                  </span>
                  <span className="text-[0.65rem] text-muted-foreground/70">
                    {formatRelative(alert.created_at)}
                    {alert.occurrence_count > 1 ? ` · ×${alert.occurrence_count}` : ''}
                    {alert.escalated_from ? ` · escalated from ${alert.escalated_from}` : ''}
                  </span>
                </Link>
              </DropdownMenuItem>
            ))}
          </div>
        )}
        <DropdownMenuSeparator className="mx-0 my-0" />
        <DropdownMenuItem asChild className="justify-center px-3 py-2 text-xs">
          <Link href="/alerts">Open the alert queue</Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
