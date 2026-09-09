'use client';

import { AlertTriangle } from 'lucide-react';
import * as React from 'react';

import { Button } from '@/components/ui/button';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  React.useEffect(() => {
    // Surfacing to the console is the honest option here: this prototype has
    // no error-reporting backend, and pretending otherwise would be worse.
    console.error('Unhandled UI error', error);
  }, [error]);

  return (
    <div className="grid min-h-[60vh] place-items-center px-6">
      <div className="glass max-w-lg space-y-4 p-8 text-center">
        <div className="mx-auto w-fit rounded-full bg-destructive/10 p-3">
          <AlertTriangle className="size-6 text-destructive" />
        </div>
        <h1 className="text-lg font-semibold">This screen hit an unexpected error</h1>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {error.message || 'No further detail is available.'}
          {error.digest ? (
            <span className="mt-2 block font-mono text-[0.65rem] opacity-70">
              digest {error.digest}
            </span>
          ) : null}
        </p>
        <Button onClick={reset}>Try again</Button>
      </div>
    </div>
  );
}
