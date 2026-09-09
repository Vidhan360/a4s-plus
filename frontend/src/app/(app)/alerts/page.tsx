'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellOff, CheckCheck, Gavel, Layers, Siren, TimerReset } from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';
import { toast } from 'sonner';

import { RiskBadge } from '@/components/domain/risk-badge';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { StatCard } from '@/components/ui/stat-card';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { errorMessage } from '@/lib/api-error';
import { PERM } from '@/lib/constants';
import { formatDuration, formatInt, formatRelative } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Alert, AlertSummary, Paged } from '@/lib/types';

const PAGE_SIZE = 20;
const STATUSES = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED'];
const SEVERITIES = ['INFO', 'WARNING', 'CRITICAL', 'EMERGENCY'];

interface AlertRules {
  rules: Record<string, unknown>;
  behaviour: string[] | Record<string, string>;
}

function ResolveDialog({
  alert,
  onClose,
  onDone,
}: {
  alert: Alert | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [note, setNote] = React.useState('');

  const mutation = useMutation({
    mutationFn: () => api.post<Alert>(`/alerts/${alert?.id}/resolve`, { resolution_note: note }),
    onSuccess: () => {
      toast.success('Alert resolved', {
        description: 'The resolution note is on the audit trail.',
      });
      setNote('');
      onDone();
      onClose();
    },
    onError: (error) => toast.error('Could not resolve', { description: errorMessage(error) }),
  });

  return (
    <Dialog open={Boolean(alert)} onOpenChange={(open) => (open ? undefined : onClose())}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Resolve alert</DialogTitle>
          <DialogDescription>
            A resolution note is required. It is stored on the alert and written to the append-only
            audit log with your identity.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <p className="rounded-md border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-xs">
            {alert?.title}
          </p>
          <div className="space-y-1.5">
            <Label htmlFor="resolution-note">Resolution note</Label>
            <Textarea
              id="resolution-note"
              required
              minLength={3}
              placeholder="Casualty descended to 4,200 m and SpO₂ recovered to 94%."
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending} data-testid="confirm-resolve">
              Resolve alert
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function AlertsPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [status, setStatus] = React.useState('OPEN');
  const [severity, setSeverity] = React.useState('ALL');
  const [page, setPage] = React.useState(0);
  const [resolving, setResolving] = React.useState<Alert | null>(null);

  const params = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    status: status === 'ALL' ? undefined : status,
    severity: severity === 'ALL' ? undefined : severity,
  };

  const alerts = useQuery({
    queryKey: qk.alerts(params),
    queryFn: () => api.get<Paged<Alert>>('/alerts', params),
    enabled: can(PERM.alertRead),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  const summary = useQuery({
    queryKey: qk.alertSummary,
    queryFn: () => api.get<AlertSummary>('/alerts/summary'),
    enabled: can(PERM.alertRead),
    refetchInterval: 15_000,
  });

  const rules = useQuery({
    queryKey: qk.alertRules,
    queryFn: () => api.get<AlertRules>('/alerts/rules'),
    enabled: can(PERM.alertRead),
    staleTime: 60_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['alerts'] });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const acknowledge = useMutation({
    mutationFn: (id: string) => api.post<Alert>(`/alerts/${id}/acknowledge`, {}),
    onSuccess: () => {
      toast.success('Alert acknowledged');
      invalidate();
    },
    onError: (error) => toast.error('Could not acknowledge', { description: errorMessage(error) }),
  });

  if (!can(PERM.alertRead)) {
    return <EmptyState title="Your role does not include the alert queue" />;
  }

  const total = alerts.data?.meta.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        description="The alert engine deduplicates by a stable key, suppresses repeats inside a cooldown window, and escalates severity when a condition persists. Nothing here is a notification to a real device."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Open"
          value={formatInt(summary.data?.open)}
          icon={Siren}
          accent={(summary.data?.open ?? 0) > 0 ? 'high' : 'low'}
          loading={summary.isLoading}
        />
        <StatCard
          label="Critical open"
          value={formatInt(summary.data?.critical.length)}
          icon={Gavel}
          accent="critical"
          loading={summary.isLoading}
        />
        <StatCard
          label="Emergency severity"
          value={formatInt(summary.data?.by_severity?.EMERGENCY ?? 0)}
          accent="critical"
          loading={summary.isLoading}
        />
        <StatCard
          label="Types seen (24 h)"
          value={formatInt(Object.keys(summary.data?.by_type_24h ?? {}).length)}
          icon={Layers}
          loading={summary.isLoading}
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <CardTitle>Alert queue</CardTitle>
              <CardDescription>
                Acknowledge to claim an alert; resolve to close it with a mandatory note.
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-[170px] space-y-1.5">
                <Label htmlFor="alert-status">Status</Label>
                <Select
                  value={status}
                  onValueChange={(value) => {
                    setStatus(value);
                    setPage(0);
                  }}
                >
                  <SelectTrigger id="alert-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All statuses</SelectItem>
                    {STATUSES.map((entry) => (
                      <SelectItem key={entry} value={entry}>
                        {entry}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="w-[170px] space-y-1.5">
                <Label htmlFor="alert-severity">Severity</Label>
                <Select
                  value={severity}
                  onValueChange={(value) => {
                    setSeverity(value);
                    setPage(0);
                  }}
                >
                  <SelectTrigger id="alert-severity">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ALL">All severities</SelectItem>
                    {SEVERITIES.map((entry) => (
                      <SelectItem key={entry} value={entry}>
                        {entry}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {alerts.isLoading ? (
            <LoadingPanel rows={8} />
          ) : alerts.isError ? (
            <ErrorPanel error={alerts.error} onRetry={() => void alerts.refetch()} />
          ) : (alerts.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="Nothing in this view"
              description="No alert matches the current filters. Start the simulation, or inject a manual reading with poor vitals, to generate alerts."
              icon={BellOff}
            />
          ) : (
            <>
              <Table data-testid="alerts-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Alert</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Seen</TableHead>
                    <TableHead className="text-right">Last triggered</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(alerts.data?.items ?? []).map((alert) => (
                    <TableRow key={alert.id}>
                      <TableCell className="max-w-[420px]">
                        <p className="text-xs font-medium">{alert.title}</p>
                        <p className="mt-0.5 line-clamp-2 text-[0.68rem] leading-relaxed text-muted-foreground">
                          {alert.reason}
                        </p>
                        <p className="mt-0.5 text-[0.66rem] text-primary/90">
                          {alert.recommended_action}
                        </p>
                        {alert.personnel_id ? (
                          <Link
                            href={`/personnel/${alert.personnel_id}`}
                            className="mt-1 inline-block text-[0.66rem] text-primary hover:underline"
                          >
                            Open soldier
                          </Link>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <RiskBadge category={alert.severity} pulse />
                      </TableCell>
                      <TableCell>
                        <Badge variant={alert.status === 'OPEN' ? 'default' : 'secondary'}>
                          {alert.status}
                        </Badge>
                        {alert.escalated_from ? (
                          <p className="mt-1 text-[0.62rem] text-muted-foreground">
                            escalated from {alert.escalated_from}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell className="font-mono text-[0.68rem] text-muted-foreground">
                        {alert.alert_type}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs tabular-nums">
                        ×{alert.occurrence_count}
                      </TableCell>
                      <TableCell className="text-right text-[0.68rem] text-muted-foreground">
                        {formatRelative(alert.last_triggered_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1.5">
                          {can(PERM.alertAck) && alert.status === 'OPEN' ? (
                            <Button
                              size="sm"
                              variant="outline"
                              loading={acknowledge.isPending}
                              onClick={() => acknowledge.mutate(alert.id)}
                              data-testid="acknowledge-alert"
                            >
                              <CheckCheck />
                              Ack
                            </Button>
                          ) : null}
                          {can(PERM.alertAck) && alert.status !== 'RESOLVED' ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setResolving(alert)}
                              data-testid="resolve-alert"
                            >
                              Resolve
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <div className="mt-4 flex items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  {total} alert{total === 1 ? '' : 's'} in this view
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page === 0}
                    onClick={() => setPage((value) => Math.max(0, value - 1))}
                  >
                    Previous
                  </Button>
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {page + 1} / {pageCount}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={page + 1 >= pageCount}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TimerReset className="size-3.5 text-primary" />
            Live engine configuration
          </CardTitle>
          <CardDescription>
            Read straight from the runtime configuration table, so what you see is what the engine
            is using right now.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {rules.isLoading ? (
            <LoadingPanel rows={3} />
          ) : rules.isError ? (
            <ErrorPanel error={rules.error} onRetry={() => void rules.refetch()} />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(rules.data?.rules ?? {}).map(([key, value]) => (
                  <div
                    key={key}
                    className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2"
                  >
                    <p className="label-muted">{key.replace(/_/g, ' ')}</p>
                    <p className="mt-0.5 break-words font-mono text-xs">
                      {typeof value === 'object'
                        ? JSON.stringify(value)
                        : key.includes('seconds')
                          ? formatDuration(Number(value))
                          : String(value)}
                    </p>
                  </div>
                ))}
              </div>
              <ul className="space-y-1.5">
                {(Array.isArray(rules.data?.behaviour)
                  ? rules.data.behaviour
                  : Object.values(rules.data?.behaviour ?? {})
                ).map((line, index) => (
                  <li
                    key={index}
                    className="flex gap-2 text-[0.7rem] leading-relaxed text-muted-foreground"
                  >
                    <span className="text-primary">•</span>
                    {String(line)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </CardContent>
      </Card>

      <ResolveDialog alert={resolving} onClose={() => setResolving(null)} onDone={invalidate} />
    </div>
  );
}
