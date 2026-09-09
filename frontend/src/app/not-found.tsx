import Link from 'next/link';

import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center px-6">
      <div className="glass max-w-md space-y-4 p-8 text-center">
        <p className="font-mono text-4xl font-semibold text-primary">404</p>
        <h1 className="text-lg font-semibold">That screen does not exist</h1>
        <p className="text-xs leading-relaxed text-muted-foreground">
          The console only exposes the modules your role is permitted to see. If you followed a
          link from a demo script, the module may have been renamed.
        </p>
        <Button asChild>
          <Link href="/dashboard">Back to the command dashboard</Link>
        </Button>
      </div>
    </div>
  );
}
