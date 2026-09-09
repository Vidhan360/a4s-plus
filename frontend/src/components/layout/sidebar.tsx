'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import * as React from 'react';

import { Brand } from '@/components/layout/brand';
import { NAV_SECTIONS } from '@/components/layout/nav-items';
import { useSession } from '@/hooks/use-session';
import { cn } from '@/lib/utils';

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { canAny } = useSession();

  const sections = React.useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        ...section,
        items: section.items.filter((item) => canAny(...item.permissions)),
      })).filter((section) => section.items.length > 0),
    [canAny],
  );

  return (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 pb-6" aria-label="Main">
      {sections.map((section) => (
        <div key={section.title} className="space-y-1">
          <p className="label-muted px-3 py-1">{section.title}</p>
          {section.items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? 'page' : undefined}
                title={item.description}
                className={cn(
                  'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all',
                  active
                    ? 'bg-primary/12 font-medium text-primary shadow-[inset_2px_0_0_0_hsl(var(--primary))]'
                    : 'text-muted-foreground hover:bg-white/[0.05] hover:text-foreground',
                )}
              >
                <Icon
                  className={cn(
                    'size-4 shrink-0 transition-colors',
                    active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground',
                  )}
                />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function DesktopSidebar() {
  return (
    <aside className="hidden w-[268px] shrink-0 flex-col border-r border-white/[0.06] bg-card/40 backdrop-blur-xl lg:flex">
      <div className="px-5 py-5">
        <Link href="/dashboard" className="block rounded-lg">
          <Brand />
        </Link>
      </div>
      <div className="hairline" />
      <div className="min-h-0 flex-1 pt-4">
        <SidebarNav />
      </div>
    </aside>
  );
}
