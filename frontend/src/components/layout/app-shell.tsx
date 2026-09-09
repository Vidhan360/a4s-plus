'use client';

import { useRouter } from 'next/navigation';
import * as React from 'react';

import { PrototypeBanner } from '@/components/layout/prototype-banner';
import { DesktopSidebar } from '@/components/layout/sidebar';
import { Topbar } from '@/components/layout/topbar';
import { Skeleton } from '@/components/ui/skeleton';
import { LiveStreamProvider } from '@/hooks/use-live-stream';
import { useSession } from '@/hooks/use-session';
import { DISCLAIMERS } from '@/lib/constants';

function ShellSkeleton() {
  return (
    <div className="flex min-h-screen" role="status" aria-busy="true">
      <div className="hidden w-[268px] border-r border-white/[0.06] p-5 lg:block">
        <Skeleton className="h-9 w-40" />
        <div className="mt-8 space-y-2">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-6">
        <Skeleton className="h-8 w-56" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
        <Skeleton className="mt-4 h-72 w-full" />
      </div>
    </div>
  );
}

/**
 * Authenticated application shell.
 *
 * Route protection is client-side because the backend is a stateless JWT API
 * and the token lives in the browser. The API itself is the real enforcement
 * point — every request is authorised server-side — so this guard is about
 * user experience, not security.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useSession();
  const router = useRouter();

  React.useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [loading, user, router]);

  if (loading || !user) return <ShellSkeleton />;

  return (
    <LiveStreamProvider enabled>
      <div className="flex min-h-screen flex-col">
        <PrototypeBanner />
        <div className="flex min-h-0 flex-1">
          <DesktopSidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <Topbar />
            <main className="min-w-0 flex-1 px-4 py-6 lg:px-6">
              <div className="mx-auto w-full max-w-[1560px] space-y-6">{children}</div>
            </main>
            <footer className="border-t border-white/[0.06] px-4 py-4 lg:px-6">
              <p className="mx-auto max-w-[1560px] text-[0.68rem] leading-relaxed text-muted-foreground">
                {DISCLAIMERS.long}
              </p>
            </footer>
          </div>
        </div>
      </div>
    </LiveStreamProvider>
  );
}
