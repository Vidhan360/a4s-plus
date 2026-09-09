import { AppShell } from '@/components/layout/app-shell';

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <div id="main-content">{children}</div>
    </AppShell>
  );
}
