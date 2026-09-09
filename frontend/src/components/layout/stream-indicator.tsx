'use client';

import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useLiveStream } from '@/hooks/use-live-stream';
import { formatRelative } from '@/lib/format';
import { cn } from '@/lib/utils';

const COPY: Record<string, { label: string; dot: string; detail: string }> = {
  live: { label: 'Live', dot: 'bg-risk-low', detail: 'Connected to the event stream.' },
  connecting: {
    label: 'Connecting',
    dot: 'bg-risk-moderate animate-pulse',
    detail: 'Opening the event stream…',
  },
  reconnecting: {
    label: 'Reconnecting',
    dot: 'bg-risk-high animate-pulse',
    detail: 'The stream dropped. Retrying with exponential backoff.',
  },
  offline: { label: 'Offline', dot: 'bg-muted-foreground', detail: 'No live stream.' },
};

export function StreamIndicator() {
  const { status, backend, lastFrameAt, attempts, topics, reconnect } = useLiveStream();
  const copy = COPY[status] ?? COPY.offline;

  return (
    <div className="flex items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            data-testid="stream-indicator"
            data-status={status}
            className="flex items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-wider"
          >
            <span className={cn('size-1.5 rounded-full', copy.dot)} />
            {copy.label}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <p>{copy.detail}</p>
          {backend ? <p className="mt-1 opacity-80">Bus: {backend}</p> : null}
          {topics.length ? <p className="opacity-80">Topics: {topics.join(', ')}</p> : null}
          <p className="opacity-80">Last frame {formatRelative(lastFrameAt)}</p>
          {attempts > 0 ? <p className="opacity-80">Retries: {attempts}</p> : null}
        </TooltipContent>
      </Tooltip>
      {status === 'live' ? null : (
        <Button size="icon-sm" variant="ghost" onClick={reconnect} aria-label="Reconnect stream">
          <RefreshCw className="size-3.5" />
        </Button>
      )}
    </div>
  );
}
