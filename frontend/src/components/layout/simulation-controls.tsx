'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Gauge, Pause, Play, RotateCcw, Square } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { errorMessage } from '@/lib/api-error';
import { PERM, SIM_SPEEDS } from '@/lib/constants';
import { qk } from '@/lib/query-keys';
import type { SimulationStatus } from '@/lib/types';
import { cn } from '@/lib/utils';

export const DEFAULT_SEED = 20260909;

export function useSimulationStatus(enabled: boolean) {
  return useQuery({
    queryKey: qk.simulationStatus,
    queryFn: () => api.get<SimulationStatus>('/simulation/status'),
    enabled,
    refetchInterval: 5000,
  });
}

/** Compact START/PAUSE/STOP/RESET + speed control used in the top bar. */
export function SimulationControls({ compact = false }: { compact?: boolean }) {
  const { can } = useSession();
  const mayRead = can(PERM.simulationRead);
  const mayControl = can(PERM.simulationControl);
  const queryClient = useQueryClient();
  const { data: status } = useSimulationStatus(mayRead);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.simulationStatus });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const control = useMutation({
    mutationFn: (input: { action: string; body?: unknown }) =>
      api.post<SimulationStatus>(`/simulation/${input.action}`, input.body ?? {}),
    onSuccess: (data, input) => {
      queryClient.setQueryData(qk.simulationStatus, data);
      invalidate();
      toast.success(`Simulation ${input.action}`, {
        description: `Engine state: ${data.status}${data.seed === null ? '' : ` · seed ${data.seed}`}`,
      });
    },
    onError: (error) => toast.error('Simulation control failed', { description: errorMessage(error) }),
  });

  if (!mayRead) return null;

  const state = status?.status ?? 'IDLE';
  const running = state === 'RUNNING';
  const paused = state === 'PAUSED';
  const disabled = control.isPending || !mayControl;

  return (
    <div
      className="flex items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.03] p-1"
      data-testid="simulation-controls"
      data-sim-status={state}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="px-2 font-mono text-[0.68rem] font-semibold uppercase tracking-wider text-muted-foreground">
            <span
              className={cn(
                'mr-1.5 inline-block size-1.5 rounded-full align-middle',
                running ? 'bg-risk-low' : paused ? 'bg-risk-moderate' : 'bg-muted-foreground',
              )}
            />
            {state}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <p>Simulation engine state.</p>
          <p className="opacity-80">
            Tick {status?.tick_count ?? 0} · {status?.readings_emitted ?? 0} readings ·{' '}
            {status?.alerts_raised ?? 0} alerts
          </p>
          {status?.seed === null || status?.seed === undefined ? null : (
            <p className="opacity-80">Seed {status.seed} — reruns reproduce this trajectory.</p>
          )}
        </TooltipContent>
      </Tooltip>

      {running ? (
        <Button
          size="icon-sm"
          variant="ghost"
          disabled={disabled}
          onClick={() => control.mutate({ action: 'pause' })}
          aria-label="Pause simulation"
        >
          <Pause className="size-3.5" />
        </Button>
      ) : (
        <Button
          size="icon-sm"
          variant="ghost"
          disabled={disabled}
          onClick={() =>
            control.mutate(
              paused
                ? { action: 'resume' }
                : {
                    action: 'start',
                    body: { scenario: 'MIXED', seed: DEFAULT_SEED, speed: 2, reset_first: true },
                  },
            )
          }
          aria-label={paused ? 'Resume simulation' : 'Start simulation'}
        >
          <Play className="size-3.5" />
        </Button>
      )}

      <Button
        size="icon-sm"
        variant="ghost"
        disabled={disabled}
        onClick={() => control.mutate({ action: 'stop' })}
        aria-label="Stop simulation"
      >
        <Square className="size-3.5" />
      </Button>

      {compact ? null : (
        <Button
          size="icon-sm"
          variant="ghost"
          disabled={disabled}
          onClick={() => control.mutate({ action: 'reset' })}
          aria-label="Reset simulation"
        >
          <RotateCcw className="size-3.5" />
        </Button>
      )}

      <Select
        value={String(status?.speed ?? 1)}
        disabled={disabled}
        onValueChange={(value) => control.mutate({ action: 'speed', body: { speed: Number(value) } })}
      >
        <SelectTrigger
          className="h-7 w-[74px] border-0 bg-transparent px-2 text-xs shadow-none"
          aria-label="Simulation speed"
        >
          <Gauge className="size-3.5 opacity-60" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SIM_SPEEDS.map((speed) => (
            <SelectItem key={speed} value={String(speed)}>
              {speed}×
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
