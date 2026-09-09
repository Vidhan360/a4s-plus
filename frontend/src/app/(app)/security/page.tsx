'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  BadgeCheck,
  KeyRound,
  Lock,
  ShieldAlert,
  ShieldCheck,
  Siren,
  UserX,
} from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/layout/page-header';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
import { errorMessage } from '@/lib/api-error';
import { PERM } from '@/lib/constants';
import { formatDateTime, formatInt, formatNumber, formatRelative, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { CryptoDemoResult, Paged, SecurityEvent, SecurityPosture } from '@/lib/types';

interface Catalogue {
  simulated_events: {
    kind: string;
    event_type: string;
    severity: string;
    title: string;
    description: string;
  }[];
  automatic_responses: Record<string, string>;
  origin_semantics: Record<string, string>;
}

interface SecuritySettings {
  access_token_minutes: number;
  refresh_token_days: number;
  max_failed_logins: number;
  lockout_minutes: number;
  min_password_length: number;
  password_hash: string;
  environment: string;
  controls: { control: string; status: string; detail: string }[];
}

const SEV_VARIANT: Record<string, 'low' | 'moderate' | 'high' | 'critical'> = {
  LOW: 'low',
  MEDIUM: 'moderate',
  HIGH: 'high',
  CRITICAL: 'critical',
};

const STATUS_VARIANT: Record<string, 'outline' | 'moderate' | 'low'> = {
  NEW: 'moderate',
  INVESTIGATING: 'moderate',
  MITIGATED: 'low',
  CLOSED: 'outline',
};

/** Security monitor: posture, event triage, injection harness and AEAD demonstration. */
export default function SecurityPage() {
  const { can } = useSession();
  const queryClient = useQueryClient();
  const canSimulate = can(PERM.securitySimulate);
  const canTriage = can(PERM.securityWrite);
  const canCrypto = can(PERM.cryptoDemo);

  const [severity, setSeverity] = React.useState('all');
  const [origin, setOrigin] = React.useState('all');
  const [status, setStatus] = React.useState('all');
  const [injectKind, setInjectKind] = React.useState('');
  const [plaintext, setPlaintext] = React.useState('CASEVAC grid 42-17, two casualties, HAPE suspected');
  const [aad, setAad] = React.useState('mission:alpha-7');

  const posture = useQuery<SecurityPosture>({
    queryKey: qk.securityPosture,
    queryFn: () => api.get<SecurityPosture>('/security/posture'),
    refetchInterval: 20000,
  });

  const eventParams = {
    limit: 50,
    offset: 0,
    ...(severity !== 'all' ? { severity } : {}),
    ...(origin !== 'all' ? { origin } : {}),
    ...(status !== 'all' ? { status } : {}),
  };

  const events = useQuery<Paged<SecurityEvent>>({
    queryKey: qk.securityEvents(eventParams),
    queryFn: () => api.get<Paged<SecurityEvent>>('/security/events', eventParams),
  });

  const catalogue = useQuery<Catalogue>({
    queryKey: qk.securityCatalogue,
    queryFn: () => api.get<Catalogue>('/security/catalogue'),
    staleTime: 60 * 60 * 1000,
  });

  const settings = useQuery<SecuritySettings>({
    queryKey: qk.securitySettings,
    queryFn: () => api.get<SecuritySettings>('/security/settings'),
    staleTime: 10 * 60 * 1000,
  });

  React.useEffect(() => {
    if (!injectKind && catalogue.data?.simulated_events.length) {
      setInjectKind(catalogue.data.simulated_events[0].kind);
    }
  }, [catalogue.data, injectKind]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['security'] });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const inject = useMutation({
    mutationFn: () => api.post<SecurityEvent>('/security/inject', { kind: injectKind }),
    onSuccess: (event) => {
      toast.warning('Simulated event raised', { description: event.title });
      invalidate();
    },
    onError: (error) => toast.error('Injection failed', { description: errorMessage(error) }),
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) =>
      api.post<SecurityEvent>(`/security/events/${id}/acknowledge`, {
        note: 'Reviewed from the security monitor.',
      }),
    onSuccess: () => {
      toast.success('Event marked mitigated');
      invalidate();
    },
    onError: (error) => toast.error('Could not update event', { description: errorMessage(error) }),
  });

  const crypto = useMutation({
    mutationFn: () =>
      api.post<CryptoDemoResult>('/security/crypto-demo', {
        plaintext,
        aad: aad.trim() === '' ? null : aad,
      }),
    onError: (error) => toast.error('Demo failed', { description: errorMessage(error) }),
  });

  const rows = events.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Security monitor"
        description="Two classes of event are shown side by side: REAL events produced by this application's own controls (failed sign-ins, permission denials, refresh-token reuse) and SIMULATED events injected for demonstration. The origin column always tells you which is which."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Open events"
          value={formatInt(posture.data?.open_events ?? 0)}
          hint="Status NEW or INVESTIGATING"
          icon={ShieldAlert}
          accent={(posture.data?.open_events ?? 0) > 0 ? 'high' : 'low'}
          loading={posture.isLoading}
        />
        <StatCard
          label="Critical severity"
          value={formatInt(posture.data?.by_severity?.CRITICAL ?? 0)}
          hint={`${formatInt(posture.data?.by_severity?.HIGH ?? 0)} high`}
          icon={Siren}
          accent="critical"
          loading={posture.isLoading}
        />
        <StatCard
          label="Failed sign-ins (24 h)"
          value={formatInt(posture.data?.failed_logins_24h ?? 0)}
          hint="Real authentication telemetry"
          icon={UserX}
          loading={posture.isLoading}
        />
        <StatCard
          label="Locked accounts"
          value={formatInt(posture.data?.locked_accounts ?? 0)}
          hint={`Lockout after ${settings.data?.max_failed_logins ?? '—'} failures`}
          icon={Lock}
          loading={posture.isLoading}
        />
      </div>

      <Tabs defaultValue="events">
        <TabsList>
          <TabsTrigger value="events" data-testid="tab-events">
            Event log
          </TabsTrigger>
          <TabsTrigger value="controls">Controls</TabsTrigger>
          <TabsTrigger value="crypto" data-testid="tab-crypto">
            Encryption demo
          </TabsTrigger>
        </TabsList>

        <TabsContent value="events" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="glass">
              <CardHeader className="gap-3">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <CardTitle>Security events</CardTitle>
                    <CardDescription>
                      {formatInt(events.data?.meta.total ?? 0)} matching events
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Select value={severity} onValueChange={setSeverity}>
                      <SelectTrigger className="w-32" aria-label="Severity">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All severities</SelectItem>
                        {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((s) => (
                          <SelectItem key={s} value={s}>
                            {titleCase(s)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={origin} onValueChange={setOrigin}>
                      <SelectTrigger className="w-32" data-testid="origin-filter" aria-label="Origin">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All origins</SelectItem>
                        <SelectItem value="REAL">Real</SelectItem>
                        <SelectItem value="SIMULATED">Simulated</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select value={status} onValueChange={setStatus}>
                      <SelectTrigger className="w-36" aria-label="Status">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        {['NEW', 'INVESTIGATING', 'MITIGATED', 'CLOSED'].map((s) => (
                          <SelectItem key={s} value={s}>
                            {titleCase(s)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="px-0">
                {events.isLoading ? (
                  <LoadingPanel label="Loading events…" rows={6} />
                ) : events.error ? (
                  <ErrorPanel error={events.error} onRetry={() => events.refetch()} />
                ) : rows.length === 0 ? (
                  <EmptyState
                    title="No security events match"
                    description="Relax the filters, or inject a simulated event to exercise the detection path."
                  />
                ) : (
                  <Table data-testid="security-events">
                    <TableHeader>
                      <TableRow>
                        <TableHead>Event</TableHead>
                        <TableHead>Origin</TableHead>
                        <TableHead>Severity</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Automatic response</TableHead>
                        <TableHead className="text-right">When</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {rows.map((e) => (
                        <TableRow key={e.id}>
                          <TableCell className="max-w-xs">
                            <p className="truncate font-medium">{e.title}</p>
                            <p className="truncate text-xs text-muted-foreground">
                              {e.description}
                            </p>
                          </TableCell>
                          <TableCell>
                            <Badge variant={e.origin === 'REAL' ? 'high' : 'outline'}>
                              {titleCase(e.origin)}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={SEV_VARIANT[e.severity] ?? 'outline'}>
                              {titleCase(e.severity)}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={STATUS_VARIANT[e.status] ?? 'outline'}>
                              {titleCase(e.status)}
                            </Badge>
                          </TableCell>
                          <TableCell className="max-w-[14rem] text-xs text-muted-foreground">
                            {e.response_action ?? '—'}
                          </TableCell>
                          <TableCell className="text-right text-xs text-muted-foreground">
                            {formatRelative(e.created_at)}
                          </TableCell>
                          <TableCell className="text-right">
                            {e.status === 'NEW' || e.status === 'INVESTIGATING' ? (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={!canTriage || acknowledge.isPending}
                                onClick={() => acknowledge.mutate(e.id)}
                                data-testid="acknowledge-security-event"
                              >
                                <BadgeCheck />
                                Mitigate
                              </Button>
                            ) : null}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card className="glass">
                <CardHeader>
                  <CardTitle>Injection harness</CardTitle>
                  <CardDescription>
                    Creates a labelled SIMULATED event. No real attack traffic is generated.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="inject-kind">Scenario</Label>
                    <Select value={injectKind} onValueChange={setInjectKind}>
                      <SelectTrigger id="inject-kind" data-testid="inject-kind">
                        <SelectValue placeholder="Select scenario" />
                      </SelectTrigger>
                      <SelectContent>
                        {(catalogue.data?.simulated_events ?? []).map((s) => (
                          <SelectItem key={s.kind} value={s.kind}>
                            {s.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  {injectKind ? (
                    <p className="text-[0.7rem] leading-relaxed text-muted-foreground">
                      {
                        catalogue.data?.simulated_events.find((s) => s.kind === injectKind)
                          ?.description
                      }
                    </p>
                  ) : null}
                  <Button
                    className="w-full"
                    onClick={() => inject.mutate()}
                    disabled={!canSimulate || !injectKind || inject.isPending}
                    data-testid="inject-security-event"
                  >
                    <Siren />
                    {inject.isPending ? 'Injecting…' : 'Inject simulated event'}
                  </Button>
                  {!canSimulate ? (
                    <p className="text-[0.7rem] text-muted-foreground">
                      Requires the <code className="font-mono">security:simulate</code> permission.
                    </p>
                  ) : null}
                </CardContent>
              </Card>

              <Card className="glass">
                <CardHeader>
                  <CardTitle>Origin semantics</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3 text-xs">
                  {Object.entries(catalogue.data?.origin_semantics ?? {}).map(([k, v]) => (
                    <div key={k} className="space-y-1">
                      <Badge variant={k === 'REAL' ? 'high' : 'outline'}>{titleCase(k)}</Badge>
                      <p className="leading-relaxed text-muted-foreground">{v}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="controls" className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="glass">
              <CardHeader>
                <CardTitle>Implemented controls</CardTitle>
                <CardDescription>
                  Only controls that actually exist in this codebase are listed
                </CardDescription>
              </CardHeader>
              <CardContent>
                {settings.isLoading ? (
                  <LoadingPanel label="Loading controls…" />
                ) : settings.error ? (
                  <ErrorPanel error={settings.error} onRetry={() => settings.refetch()} />
                ) : (
                  <ul className="space-y-3 text-xs" data-testid="security-controls">
                    {(settings.data?.controls ?? []).map((c) => (
                      <li key={c.control} className="flex gap-3">
                        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-risk-low" />
                        <div>
                          <p className="font-medium">{c.control}</p>
                          <p className="leading-relaxed text-muted-foreground">{c.detail}</p>
                          <Badge variant="outline" className="mt-1">
                            {titleCase(c.status)}
                          </Badge>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card className="glass">
                <CardHeader>
                  <CardTitle>Authentication parameters</CardTitle>
                  <CardDescription>Effective non-secret configuration</CardDescription>
                </CardHeader>
                <CardContent>
                  <dl className="space-y-2 text-xs">
                    {settings.data
                      ? (
                          [
                            ['Password hash', settings.data.password_hash],
                            ['Minimum password length', String(settings.data.min_password_length)],
                            ['Access token lifetime', `${settings.data.access_token_minutes} min`],
                            ['Refresh token lifetime', `${settings.data.refresh_token_days} days`],
                            ['Lockout threshold', `${settings.data.max_failed_logins} failures`],
                            ['Lockout duration', `${settings.data.lockout_minutes} min`],
                            ['Environment', settings.data.environment],
                          ] as const
                        ).map(([k, v]) => (
                          <div key={k} className="flex items-center justify-between gap-3">
                            <dt className="text-muted-foreground">{k}</dt>
                            <dd className="font-mono">{v}</dd>
                          </div>
                        ))
                      : null}
                  </dl>
                </CardContent>
              </Card>

              <Card className="glass">
                <CardHeader>
                  <CardTitle>Automatic responses</CardTitle>
                  <CardDescription>
                    Response text attached to each detected event type
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  {Object.entries(catalogue.data?.automatic_responses ?? {}).map(([k, v]) => (
                    <div key={k}>
                      <p className="font-medium">{titleCase(k)}</p>
                      <p className="leading-relaxed text-muted-foreground">{v}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="crypto" className="space-y-4">
          <Alert>
            <KeyRound />
            <AlertTitle>Authenticated encryption demonstration</AlertTitle>
            <AlertDescription>
              This panel runs AES-256-GCM over text you supply, with a key generated per request and
              discarded afterwards. It demonstrates confidentiality, integrity and tamper detection.
              It is <strong>not</strong> the transport or storage encryption of this prototype:
              application data is stored unencrypted at rest in PostgreSQL. Nothing here should be
              described as &ldquo;military-grade&rdquo; — it is a standard, publicly specified cipher.
            </AlertDescription>
          </Alert>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <Card className="glass">
              <CardHeader>
                <CardTitle>Input</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="plaintext">Plaintext</Label>
                  <Input
                    id="plaintext"
                    value={plaintext}
                    onChange={(e) => setPlaintext(e.target.value)}
                    data-testid="crypto-plaintext"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="aad">Additional authenticated data (optional)</Label>
                  <Input id="aad" value={aad} onChange={(e) => setAad(e.target.value)} />
                  <p className="text-[0.7rem] text-muted-foreground">
                    AAD is integrity-protected but not encrypted — useful for routing headers.
                  </p>
                </div>
                <Button
                  className="w-full"
                  onClick={() => crypto.mutate()}
                  disabled={!canCrypto || plaintext.trim() === '' || crypto.isPending}
                  data-testid="run-crypto-demo"
                >
                  <KeyRound />
                  {crypto.isPending ? 'Running…' : 'Encrypt, decrypt and tamper-test'}
                </Button>
                {!canCrypto ? (
                  <p className="text-[0.7rem] text-muted-foreground">
                    Requires the <code className="font-mono">crypto:demo</code> permission.
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card className="glass">
              <CardHeader>
                <CardTitle>Result</CardTitle>
                <CardDescription>
                  {crypto.data?.label ?? 'Run the demo to see measured output'}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {crypto.data ? (
                  <div className="space-y-3 text-xs" data-testid="crypto-result">
                    <dl className="space-y-2">
                      {(
                        [
                          ['Algorithm', crypto.data.algorithm],
                          ['Key size', `${crypto.data.key_bits} bits`],
                          ['Nonce size', `${crypto.data.nonce_bits} bits`],
                          ['Auth tag', `${crypto.data.tag_bytes} bytes`],
                          ['Plaintext length', `${crypto.data.plaintext_length} bytes`],
                          ['Ciphertext length', `${crypto.data.ciphertext_length} bytes`],
                          ['Encrypt time', `${formatNumber(crypto.data.encrypt_ms, 3)} ms`],
                          ['Decrypt time', `${formatNumber(crypto.data.decrypt_ms, 3)} ms`],
                        ] as const
                      ).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between gap-3">
                          <dt className="text-muted-foreground">{k}</dt>
                          <dd className="font-mono">{v}</dd>
                        </div>
                      ))}
                    </dl>
                    <div className="space-y-1">
                      <p className="label-muted">Ciphertext (base64)</p>
                      <p className="break-all rounded-md border border-white/[0.08] bg-black/30 p-2 font-mono text-[0.65rem]">
                        {crypto.data.ciphertext_b64}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={crypto.data.decrypted_matches_input ? 'low' : 'critical'}>
                        {crypto.data.decrypted_matches_input
                          ? 'Round-trip verified'
                          : 'Round-trip failed'}
                      </Badge>
                      {Object.entries(crypto.data.tamper_test).map(([k, v]) => (
                        <Badge key={k} variant="outline">
                          {titleCase(k)}: {String(v)}
                        </Badge>
                      ))}
                    </div>
                    <p className="leading-relaxed text-muted-foreground">{crypto.data.notice}</p>
                  </div>
                ) : (
                  <EmptyState
                    title="No result yet"
                    description="Encrypt something to see the measured timings and tamper-detection outcome."
                  />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <Card className="glass">
        <CardHeader>
          <CardTitle>Recent posture snapshot</CardTitle>
          <CardDescription>Latest events counted in the posture summary</CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {(posture.data?.recent.length ?? 0) === 0 ? (
            <EmptyState title="Nothing recent" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Title</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Origin</TableHead>
                  <TableHead className="text-right">Recorded</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {posture.data!.recent.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-medium">{e.title}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {titleCase(e.event_type)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={e.origin === 'REAL' ? 'high' : 'outline'}>
                        {titleCase(e.origin)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {formatDateTime(e.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
