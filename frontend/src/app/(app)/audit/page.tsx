'use client';

import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, FileLock2, Search, ShieldCheck } from 'lucide-react';
import * as React from 'react';

import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { EmptyState, ErrorPanel, LoadingPanel } from '@/components/ui/states';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { api } from '@/lib/api-client';
import { formatDateTime, formatInt, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { AuditLog, Paged } from '@/lib/types';

interface Facets {
  actions: string[];
  resource_types: string[];
  results: string[];
}

type AuditPage = Paged<AuditLog> & { immutability: string };

const RESULT_VARIANT: Record<string, 'low' | 'high' | 'critical'> = {
  SUCCESS: 'low',
  DENIED: 'high',
  ERROR: 'critical',
};

const PAGE_SIZE = 50;

/** Append-only audit trail viewer with faceted filtering. */
export default function AuditPage() {
  const [action, setAction] = React.useState('all');
  const [resourceType, setResourceType] = React.useState('all');
  const [result, setResult] = React.useState('all');
  const [hours, setHours] = React.useState('all');
  const [email, setEmail] = React.useState('');
  const [emailQuery, setEmailQuery] = React.useState('');
  const [offset, setOffset] = React.useState(0);
  const [detail, setDetail] = React.useState<AuditLog | null>(null);

  const facets = useQuery<Facets>({
    queryKey: qk.auditFacets,
    queryFn: () => api.get<Facets>('/audit/facets'),
    staleTime: 5 * 60 * 1000,
  });

  const params = {
    limit: PAGE_SIZE,
    offset,
    ...(action !== 'all' ? { action } : {}),
    ...(resourceType !== 'all' ? { resource_type: resourceType } : {}),
    ...(result !== 'all' ? { result } : {}),
    ...(hours !== 'all' ? { hours: Number(hours) } : {}),
    ...(emailQuery.trim() !== '' ? { actor_email: emailQuery.trim() } : {}),
  };

  const logs = useQuery<AuditPage>({
    queryKey: qk.audit(params),
    queryFn: () => api.get<AuditPage>('/audit', params),
  });

  const total = logs.data?.meta.total ?? 0;
  const rows = logs.data?.items ?? [];

  const reset = (fn: () => void) => {
    fn();
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit trail"
        description="Every privileged action — sign-ins, permission denials, personnel changes, alert transitions, simulation control, configuration edits — is written here with actor, resource, result and request ID."
      />

      <Alert>
        <FileLock2 />
        <AlertTitle>Append-only by construction</AlertTitle>
        <AlertDescription>
          {logs.data?.immutability ??
            'The API exposes no mutation path for audit records, and the database enforces append-only semantics with a trigger.'}
        </AlertDescription>
      </Alert>

      <Card className="glass">
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <CardTitle>Log entries</CardTitle>
              <CardDescription>{formatInt(total)} matching records</CardDescription>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="audit-action" className="text-[0.7rem]">
                  Action
                </Label>
                <Select value={action} onValueChange={(v) => reset(() => setAction(v))}>
                  <SelectTrigger id="audit-action" className="w-48" data-testid="audit-action">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All actions</SelectItem>
                    {(facets.data?.actions ?? []).map((a) => (
                      <SelectItem key={a} value={a}>
                        {a}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-resource" className="text-[0.7rem]">
                  Resource
                </Label>
                <Select value={resourceType} onValueChange={(v) => reset(() => setResourceType(v))}>
                  <SelectTrigger id="audit-resource" className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All resources</SelectItem>
                    {(facets.data?.resource_types ?? []).map((r) => (
                      <SelectItem key={r} value={r}>
                        {titleCase(r)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-result" className="text-[0.7rem]">
                  Result
                </Label>
                <Select value={result} onValueChange={(v) => reset(() => setResult(v))}>
                  <SelectTrigger id="audit-result" className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All results</SelectItem>
                    {(facets.data?.results ?? []).map((r) => (
                      <SelectItem key={r} value={r}>
                        {titleCase(r)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="audit-hours" className="text-[0.7rem]">
                  Window
                </Label>
                <Select value={hours} onValueChange={(v) => reset(() => setHours(v))}>
                  <SelectTrigger id="audit-hours" className="w-32">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All time</SelectItem>
                    <SelectItem value="1">Last hour</SelectItem>
                    <SelectItem value="24">Last 24 h</SelectItem>
                    <SelectItem value="168">Last 7 days</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <form
                className="flex items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  reset(() => setEmailQuery(email));
                }}
              >
                <div className="space-y-1">
                  <Label htmlFor="audit-email" className="text-[0.7rem]">
                    Actor email
                  </Label>
                  <Input
                    id="audit-email"
                    value={email}
                    placeholder="operator@a4s.local"
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-52"
                  />
                </div>
                <Button type="submit" variant="outline" size="icon" aria-label="Search">
                  <Search />
                </Button>
              </form>
            </div>
          </div>
        </CardHeader>
        <CardContent className="px-0">
          {logs.isLoading ? (
            <LoadingPanel label="Loading audit records…" rows={8} />
          ) : logs.error ? (
            <ErrorPanel error={logs.error} onRetry={() => logs.refetch()} />
          ) : rows.length === 0 ? (
            <EmptyState
              title="No audit records match"
              description="Try widening the window or clearing the filters."
            />
          ) : (
            <Table data-testid="audit-table">
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead>Request</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((log) => (
                  <TableRow
                    key={log.id}
                    className="cursor-pointer"
                    onClick={() => setDetail(log)}
                  >
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatDateTime(log.created_at)}
                    </TableCell>
                    <TableCell className="text-xs">{log.actor_email ?? 'system'}</TableCell>
                    <TableCell className="font-mono text-xs">{log.action}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {titleCase(log.resource_type)}
                      {log.resource_id ? (
                        <span className="ml-1 font-mono opacity-70">
                          {log.resource_id.slice(0, 8)}
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant={RESULT_VARIANT[log.result] ?? 'outline'}>
                        {titleCase(log.result)}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-[0.65rem] text-muted-foreground">
                      {log.request_id ? log.request_id.slice(0, 8) : '—'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {total > PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
          <span>
            Showing {formatInt(offset + 1)}–{formatInt(Math.min(offset + PAGE_SIZE, total))} of{' '}
            {formatInt(total)}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            >
              <ChevronLeft />
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              Next
              <ChevronRight />
            </Button>
          </div>
        </div>
      ) : null}

      <Dialog open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono text-sm">{detail?.action}</DialogTitle>
            <DialogDescription>
              {detail ? formatDateTime(detail.created_at) : null} ·{' '}
              {detail?.actor_email ?? 'system'}
            </DialogDescription>
          </DialogHeader>
          {detail ? (
            <div className="space-y-3 text-xs" data-testid="audit-detail">
              <dl className="grid grid-cols-2 gap-2">
                {(
                  [
                    ['Record ID', String(detail.id)],
                    ['Result', detail.result],
                    ['Resource type', detail.resource_type],
                    ['Resource ID', detail.resource_id ?? '—'],
                    ['IP', detail.ip ?? '—'],
                    ['Request ID', detail.request_id ?? '—'],
                  ] as const
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="label-muted">{k}</dt>
                    <dd className="break-all font-mono">{v}</dd>
                  </div>
                ))}
              </dl>
              {detail.user_agent ? (
                <div>
                  <p className="label-muted">User agent</p>
                  <p className="break-all font-mono text-[0.65rem]">{detail.user_agent}</p>
                </div>
              ) : null}
              <div>
                <p className="label-muted">Metadata</p>
                <pre className="max-h-64 overflow-auto rounded-md border border-white/[0.08] bg-black/40 p-3 font-mono text-[0.65rem] leading-relaxed">
                  {JSON.stringify(detail.meta, null, 2)}
                </pre>
              </div>
              <p className="flex items-center gap-2 text-muted-foreground">
                <ShieldCheck className="size-3.5" />
                This record cannot be edited or deleted through the application.
              </p>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
