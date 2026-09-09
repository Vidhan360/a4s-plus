'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RotateCcw, Save, Settings2, TriangleAlert } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { errorMessage } from '@/lib/api-error';
import { PERM } from '@/lib/constants';
import { formatDateTime, formatInt } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { ConfigEntry } from '@/lib/types';

function ConfigCard({ entry, canWrite }: { entry: ConfigEntry; canWrite: boolean }) {
  const queryClient = useQueryClient();
  const serialised = React.useMemo(() => JSON.stringify(entry.value, null, 2), [entry.value]);
  const [draft, setDraft] = React.useState(serialised);

  // Re-sync the editor whenever the server value changes (e.g. after a reset),
  // but never clobber an edit the user is part-way through typing.
  React.useEffect(() => {
    setDraft(serialised);
  }, [serialised]);

  const dirty = draft !== serialised;

  let parseError: string | null = null;
  try {
    JSON.parse(draft);
  } catch (error) {
    parseError = error instanceof Error ? error.message : 'Invalid JSON';
  }

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['config'] });
    void queryClient.invalidateQueries({ queryKey: qk.alertRules });
  };

  const save = useMutation({
    mutationFn: () =>
      api.put<ConfigEntry>(`/config/${encodeURIComponent(entry.key)}`, {
        value: JSON.parse(draft),
      }),
    onSuccess: (updated) => {
      toast.success('Configuration saved', {
        description: `${updated.key} is now at version ${updated.version}. The change is recorded in the audit trail.`,
      });
      invalidate();
    },
    onError: (error) => toast.error('Save rejected', { description: errorMessage(error) }),
  });

  const reset = useMutation({
    mutationFn: () => api.post<ConfigEntry>(`/config/${encodeURIComponent(entry.key)}/reset`, {}),
    onSuccess: () => {
      toast.success('Reset to shipped default');
      invalidate();
    },
    onError: (error) => toast.error('Reset failed', { description: errorMessage(error) }),
  });

  return (
    <Card className="glass" data-testid={`config-${entry.key}`}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="font-mono text-sm">{entry.key}</CardTitle>
            <CardDescription>{entry.description}</CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Badge variant="outline">v{entry.version}</Badge>
            {entry.is_customised ? <Badge variant="moderate">customised</Badge> : null}
            {!entry.is_editable ? <Badge variant="outline">read-only</Badge> : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={Math.min(18, draft.split('\n').length + 1)}
          spellCheck={false}
          disabled={!canWrite || !entry.is_editable}
          className="font-mono text-xs leading-relaxed"
          aria-label={`${entry.key} value`}
        />
        {parseError ? <p className="text-xs text-destructive">JSON error: {parseError}</p> : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[0.7rem] text-muted-foreground">
            {entry.updated_at ? `Last changed ${formatDateTime(entry.updated_at)}` : 'Shipped default'}
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setDraft(serialised)}
              disabled={!dirty}
            >
              Discard
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => reset.mutate()}
              disabled={!canWrite || !entry.is_editable || reset.isPending || !entry.is_customised}
              data-testid={`reset-${entry.key}`}
            >
              <RotateCcw />
              Reset
            </Button>
            <Button
              size="sm"
              onClick={() => save.mutate()}
              disabled={
                !canWrite || !entry.is_editable || !dirty || parseError !== null || save.isPending
              }
              data-testid={`save-${entry.key}`}
            >
              <Save />
              {save.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

/** Live tuning of the risk engine, alert rules, route costs and simulation defaults. */
export default function AdminConfigPage() {
  const { can } = useSession();
  const canWrite = can(PERM.configWrite);

  const config = useQuery<ConfigEntry[]>({
    queryKey: qk.config,
    queryFn: () => api.get<ConfigEntry[]>('/config'),
  });

  const entries = config.data ?? [];
  const customised = entries.filter((e) => e.is_customised).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="System configuration"
        description="Risk thresholds, factor weights, alert rules, route cost coefficients and simulation defaults are stored in the database and read by the engines at evaluation time — no redeploy is needed. Every edit is versioned and audited."
        actions={
          <Badge variant="outline" className="gap-1.5">
            <Settings2 className="size-3.5" />
            {formatInt(entries.length)} keys · {formatInt(customised)} customised
          </Badge>
        }
      />

      {!canWrite ? (
        <Alert>
          <TriangleAlert />
          <AlertTitle>Read-only</AlertTitle>
          <AlertDescription>
            Your role can read configuration but not change it. Editing requires the{' '}
            <code className="font-mono">config:write</code> permission.
          </AlertDescription>
        </Alert>
      ) : (
        <Alert>
          <TriangleAlert />
          <AlertTitle>Changes take effect immediately</AlertTitle>
          <AlertDescription>
            Saving a key bumps its version and applies it to the next risk assessment, alert
            evaluation or route plan. Values are validated server-side; an invalid shape is rejected
            with a 422 rather than silently accepted. Use Reset to return to the shipped default.
          </AlertDescription>
        </Alert>
      )}

      {config.isLoading ? (
        <LoadingPanel label="Loading configuration…" rows={8} />
      ) : config.error ? (
        <ErrorPanel error={config.error} onRetry={() => config.refetch()} />
      ) : entries.length === 0 ? (
        <EmptyState
          title="No configuration keys"
          description="Run the seed command to populate the default configuration set."
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {entries.map((entry) => (
            <ConfigCard key={entry.key} entry={entry} canWrite={canWrite} />
          ))}
        </div>
      )}
    </div>
  );
}
