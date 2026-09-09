'use client';

import { Menu, X } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';

import { Brand } from '@/components/layout/brand';
import { NAV_SECTIONS } from '@/components/layout/nav-items';
import { NotificationBell } from '@/components/layout/notification-bell';
import { SidebarNav } from '@/components/layout/sidebar';
import { SimulationControls } from '@/components/layout/simulation-controls';
import { StreamIndicator } from '@/components/layout/stream-indicator';
import { UserMenu } from '@/components/layout/user-menu';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';

function useCurrentPage() {
  const pathname = usePathname();
  return React.useMemo(() => {
    for (const section of NAV_SECTIONS) {
      for (const item of section.items) {
        if (pathname === item.href || pathname.startsWith(`${item.href}/`)) {
          return { section: section.title, ...item };
        }
      }
    }
    return null;
  }, [pathname]);
}

export function Topbar() {
  const page = useCurrentPage();
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-background/80 backdrop-blur-xl">
      <div className="flex h-14 items-center gap-3 px-4 lg:px-6">
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
        >
          <Menu className="size-4" />
        </Button>

        <div className="min-w-0 flex-1">
          {page ? (
            <div className="min-w-0">
              <p className="label-muted truncate">{page.section}</p>
              <h1 className="truncate text-sm font-semibold tracking-tight">{page.label}</h1>
            </div>
          ) : (
            <Link href="/dashboard" className="lg:hidden">
              <Brand compact />
            </Link>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden md:block">
            <SimulationControls />
          </div>
          <StreamIndicator />
          <NotificationBell />
          <UserMenu />
        </div>
      </div>

      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="left-0 top-0 h-full w-[280px] max-w-[85vw] translate-x-0 translate-y-0 rounded-none rounded-r-lg p-0">
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          <div className="flex items-center justify-between px-4 py-4">
            <Brand />
            <Button
              size="icon-sm"
              variant="ghost"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
            >
              <X className="size-4" />
            </Button>
          </div>
          <div className="hairline" />
          <div className="min-h-0 flex-1 overflow-y-auto pt-4">
            <SidebarNav onNavigate={() => setMobileOpen(false)} />
          </div>
          <div className="border-t border-white/[0.06] p-3 md:hidden">
            <SimulationControls compact />
          </div>
        </DialogContent>
      </Dialog>
    </header>
  );
}
