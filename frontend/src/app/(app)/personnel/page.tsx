'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Search, UserPlus, Users } from 'lucide-react';
import Link from 'next/link';
import * as React from 'react';
import { toast } from 'sonner';

import { ProvenanceChip } from '@/components/domain/provenance';
import { RiskBadge } from '@/components/domain/risk-badge';
import { PageHeader } from '@/components/layout/page-header';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { ApiError, errorMessage } from '@/lib/api-error';
import { PERM, RISK_CATEGORIES } from '@/lib/constants';
import { formatInt, formatNumber, formatRelative } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { Paged, PersonnelSummary } from '@/lib/types';

const PAGE_SIZE = 15;
const STATUSES = ['ACTIVE', 'RESTING', 'EVACUATED', 'CASUALTY', 'OFF_DUTY'];

function CreatePersonnelDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = React.useState(false);
  const [values, setValues] = React.useState({
    call_sign: '',
    name: '',
    age: '28',
    unit: '',
    rank: '',
  });
  const [error, setError] = React.useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<PersonnelSummary>('/personnel', {
        call_sign: values.call_sign,
        name: values.name,
        age: Number(values.age),
        unit: values.unit,
        rank: values.rank || null,
      }),
    onSuccess: (person) => {
      toast.success(`${person.call_sign} added to the roster`, {
        description: 'Telemetry will appear once the simulation reaches this person.',
      });
      setOpen(false);
      setValues({ call_sign: '', name: '', age: '28', unit: '', rank: '' });
      onCreated();
    },
    onError: (err) => {
      const fields = err instanceof ApiError ? Object.values(err.fieldErrors) : [];
      setError(fields[0] ?? errorMessage(err));
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button size="sm" onClick={() => setOpen(true)} data-testid="add-personnel">
        <UserPlus />
        Add soldier
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a soldier to the roster</DialogTitle>
          <DialogDescription>
            This creates a simulated person. Baseline heart rate and SpO₂ default to acclimatised
            values and can be tuned later.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            setError(null);
            mutation.mutate();
          }}
        >
          {(
            [
              { key: 'call_sign', label: 'Call sign', placeholder: 'GHATAK-07', required: true },
              { key: 'name', label: 'Name', placeholder: 'Naik A. Sharma', required: true },
              { key: 'age', label: 'Age', placeholder: '28', required: true, type: 'number' },
              { key: 'unit', label: 'Unit', placeholder: '5 Ladakh Scouts', required: true },
              { key: 'rank', label: 'Rank (optional)', placeholder: 'Naik', required: false },
            ] as const
          ).map((field) => (
            <div key={field.key} className="space-y-1.5">
              <Label htmlFor={`create-${field.key}`}>{field.label}</Label>
              <Input
                id={`create-${field.key}`}
                type={'type' in field ? field.type : 'text'}
                placeholder={field.placeholder}
                required={field.required}
                value={values[field.key]}
                onChange={(event) =>
                  setValues((previous) => ({ ...previous, [field.key]: event.target.value }))
                }
              />
            </div>
          ))}
          {error ? (
            <p className="sm:col-span-2 text-xs text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Add to roster
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function PersonnelPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const [search, setSearch] = React.useState('');
  const [debounced, setDebounced] = React.useState('');
  const [status, setStatus] = React.useState('ALL');
  const [risk, setRisk] = React.useState('ALL');
  const [page, setPage] = React.useState(0);

  React.useEffect(() => {
    const timer = setTimeout(() => {
      setDebounced(search.trim());
      setPage(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);

  const params = {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    search: debounced || undefined,
    status: status === 'ALL' ? undefined : status,
    risk_category: risk === 'ALL' ? undefined : risk,
  };

  const roster = useQuery({
    queryKey: qk.personnel(params),
    queryFn: () => api.get<Paged<PersonnelSummary>>('/personnel', params),
    enabled: can(PERM.personnelRead),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });

  const summary = useQuery({
    queryKey: qk.roster,
    queryFn: () =>
      api.get<{
        total: number;
        by_status: Record<string, number>;
        by_risk: Record<string, number>;
        disclaimer: string;
      }>('/personnel/summary/roster'),
    enabled: can(PERM.personnelRead),
    refetchInterval: 30_000,
  });

  if (!can(PERM.personnelRead)) {
    return (
      <EmptyState
        title="Your role does not include the roster"
        description="The personnel module requires the personnel:read permission."
      />
    );
  }

  const total = roster.data?.meta.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Personnel"
        description="Every soldier the system is tracking, with the latest risk score from the transparent rule engine and the current 30-minute forecast."
        actions={
          <>
            <ProvenanceChip source="SIMULATION" />
            {can(PERM.personnelWrite) ? (
              <CreatePersonnelDialog
                onCreated={() => {
                  void queryClient.invalidateQueries({ queryKey: ['personnel'] });
                }}
              />
            ) : null}
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Roster size"
          value={formatInt(summary.data?.total)}
          icon={Users}
          loading={summary.isLoading}
        />
        {(['LOW', 'MODERATE', 'HIGH'] as const).map((category) => (
          <StatCard
            key={category}
            label={`${category} risk`}
            value={formatInt(summary.data?.by_risk?.[category] ?? 0)}
            accent={category.toLowerCase() as 'low' | 'moderate' | 'high'}
            hint={
              category === 'HIGH'
                ? `${formatInt(summary.data?.by_risk?.CRITICAL ?? 0)} critical`
                : undefined
            }
            loading={summary.isLoading}
          />
        ))}
      </div>

      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1 space-y-1.5">
              <Label htmlFor="roster-search">Search</Label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="roster-search"
                  className="pl-8"
                  placeholder="Call sign, name or unit"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
            </div>
            <div className="w-[170px] space-y-1.5">
              <Label htmlFor="roster-status">Status</Label>
              <Select
                value={status}
                onValueChange={(value) => {
                  setStatus(value);
                  setPage(0);
                }}
              >
                <SelectTrigger id="roster-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All statuses</SelectItem>
                  {STATUSES.map((entry) => (
                    <SelectItem key={entry} value={entry}>
                      {entry.replace('_', ' ')}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[170px] space-y-1.5">
              <Label htmlFor="roster-risk">Risk band</Label>
              <Select
                value={risk}
                onValueChange={(value) => {
                  setRisk(value);
                  setPage(0);
                }}
              >
                <SelectTrigger id="roster-risk">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All bands</SelectItem>
                  {RISK_CATEGORIES.map((category) => (
                    <SelectItem key={category} value={category}>
                      {category}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="mt-5">
            {roster.isLoading ? (
              <LoadingPanel rows={8} />
            ) : roster.isError ? (
              <ErrorPanel error={roster.error} onRetry={() => void roster.refetch()} />
            ) : (roster.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                title="No matching personnel"
                description="Adjust the filters, or clear the search box to see the whole roster."
                action={
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setSearch('');
                      setStatus('ALL');
                      setRisk('ALL');
                    }}
                  >
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <>
                <Table data-testid="personnel-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Call sign</TableHead>
                      <TableHead>Unit</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Scenario</TableHead>
                      <TableHead>Risk</TableHead>
                      <TableHead className="text-right">SpO₂</TableHead>
                      <TableHead className="text-right">HR</TableHead>
                      <TableHead className="text-right">Alerts</TableHead>
                      <TableHead className="text-right">Last reading</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(roster.data?.items ?? []).map((person) => (
                      <TableRow key={person.id}>
                        <TableCell>
                          <Link
                            href={`/personnel/${person.id}`}
                            className="font-medium text-primary hover:underline"
                            data-testid="personnel-link"
                          >
                            {person.call_sign}
                          </Link>
                          <p className="text-[0.68rem] text-muted-foreground">
                            {person.name} · {person.rank ?? 'rank n/a'} · {person.age}
                          </p>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {person.unit}
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">{person.status.replace('_', ' ')}</Badge>
                        </TableCell>
                        <TableCell className="text-[0.68rem] text-muted-foreground">
                          {person.sim_scenario ?? '—'}
                        </TableCell>
                        <TableCell>
                          <RiskBadge
                            category={person.risk_category}
                            score={person.risk_score}
                            pulse
                          />
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">
                          {formatNumber(person.latest_vitals?.spo2 ?? null, 1)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">
                          {formatNumber(person.latest_vitals?.heart_rate ?? null, 0)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs tabular-nums">
                          {person.open_alert_count}
                        </TableCell>
                        <TableCell className="text-right text-[0.68rem] text-muted-foreground">
                          {formatRelative(person.last_reading_at)}
                          {person.is_stale ? (
                            <Badge variant="outline" className="ml-1.5">
                              stale
                            </Badge>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <div className="mt-4 flex items-center justify-between gap-3">
                  <p className="text-xs text-muted-foreground">
                    Showing {page * PAGE_SIZE + 1}–
                    {Math.min(total, page * PAGE_SIZE + (roster.data?.items.length ?? 0))} of{' '}
                    {total}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page === 0}
                      onClick={() => setPage((value) => Math.max(0, value - 1))}
                    >
                      <ChevronLeft />
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
                      <ChevronRight />
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {summary.data?.disclaimer ? (
        <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
          {summary.data.disclaimer}
        </p>
      ) : null}
    </div>
  );
}
