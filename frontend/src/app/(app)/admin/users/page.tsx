'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, LockOpen, Search, ShieldCheck, UserPlus } from 'lucide-react';
import * as React from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

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
  DialogTrigger,
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
import { Switch } from '@/components/ui/switch';
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
import { PERM, ROLES, ROLE_LABELS } from '@/lib/constants';
import { formatDateTime, formatInt, formatRelative, titleCase } from '@/lib/format';
import { qk } from '@/lib/query-keys';
import type { AdminUser, Paged } from '@/lib/types';

interface RoleCatalogue {
  roles: { code: string; name: string; description: string; permissions: string[] }[];
  permissions: { code: string; description: string }[];
  note: string;
}

const STATUS_VARIANT: Record<string, 'low' | 'moderate' | 'critical' | 'outline'> = {
  ACTIVE: 'low',
  DISABLED: 'outline',
  LOCKED: 'critical',
};

const createSchema = z.object({
  email: z.string().email('Enter a valid email address.'),
  full_name: z.string().min(2, 'Full name is required.').max(128),
  password: z.string().min(12, 'Passwords must be at least 12 characters.').max(256),
  role: z.enum(ROLES),
});

type CreateValues = z.infer<typeof createSchema>;

function CreateUserDialog() {
  const [open, setOpen] = React.useState(false);
  const queryClient = useQueryClient();

  const form = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { email: '', full_name: '', password: '', role: 'VIEWER' },
  });

  const mutation = useMutation({
    mutationFn: (values: CreateValues) =>
      api.post<AdminUser>('/users', {
        email: values.email,
        full_name: values.full_name,
        password: values.password,
        roles: [values.role],
      }),
    onSuccess: (user) => {
      toast.success('Account created', { description: user.email });
      void queryClient.invalidateQueries({ queryKey: ['users'] });
      setOpen(false);
      form.reset();
    },
    onError: (error) => toast.error('Could not create account', { description: errorMessage(error) }),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="add-user">
          <UserPlus />
          New account
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create account</DialogTitle>
          <DialogDescription>
            Passwords are hashed with Argon2id before storage; the plaintext is never persisted or
            logged.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
        >
          <div className="space-y-1.5">
            <Label htmlFor="new-email">Email</Label>
            <Input id="new-email" autoComplete="off" {...form.register('email')} />
            {form.formState.errors.email ? (
              <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-name">Full name</Label>
            <Input id="new-name" {...form.register('full_name')} />
            {form.formState.errors.full_name ? (
              <p className="text-xs text-destructive">{form.formState.errors.full_name.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-password">Initial password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              {...form.register('password')}
            />
            {form.formState.errors.password ? (
              <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-role">Role</Label>
            <Select
              value={form.watch('role')}
              onValueChange={(v) => form.setValue('role', v as CreateValues['role'])}
            >
              <SelectTrigger id="new-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending} data-testid="submit-user">
              {mutation.isPending ? 'Creating…' : 'Create account'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ user }: { user: AdminUser }) {
  const [open, setOpen] = React.useState(false);
  const [password, setPassword] = React.useState('');

  const mutation = useMutation({
    mutationFn: () => api.post<{ message: string }>(`/users/${user.id}/password`, { new_password: password }),
    onSuccess: () => {
      toast.success('Password reset', {
        description: `All active sessions for ${user.email} were revoked.`,
      });
      setOpen(false);
      setPassword('');
    },
    onError: (error) => toast.error('Reset failed', { description: errorMessage(error) }),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" data-testid="reset-password">
          <KeyRound />
          Reset
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>
            Sets a new password for {user.email} and revokes every refresh token issued to that
            account.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="reset-pw">New password</Label>
          <Input
            id="reset-pw"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">Minimum 12 characters.</p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={password.length < 12 || mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="confirm-reset"
          >
            {mutation.isPending ? 'Resetting…' : 'Reset password'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Account administration and the live role → permission matrix. */
export default function AdminUsersPage() {
  const { can, user: current } = useSession();
  const queryClient = useQueryClient();
  const canWrite = can(PERM.userWrite);

  const [search, setSearch] = React.useState('');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('all');
  const [roleFilter, setRoleFilter] = React.useState('all');

  const params = {
    limit: 100,
    offset: 0,
    ...(searchQuery.trim() !== '' ? { search: searchQuery.trim() } : {}),
    ...(statusFilter !== 'all' ? { status: statusFilter } : {}),
    ...(roleFilter !== 'all' ? { role: roleFilter } : {}),
  };

  const users = useQuery<Paged<AdminUser>>({
    queryKey: qk.users(params),
    queryFn: () => api.get<Paged<AdminUser>>('/users', params),
  });

  const roles = useQuery<RoleCatalogue>({
    queryKey: qk.roles,
    queryFn: () => api.get<RoleCatalogue>('/users/roles'),
    staleTime: 60 * 60 * 1000,
  });

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['users'] });

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      api.patch<AdminUser>(`/users/${id}`, patch),
    onSuccess: () => {
      toast.success('Account updated');
      invalidate();
    },
    onError: (error) => toast.error('Update failed', { description: errorMessage(error) }),
  });

  const unlock = useMutation({
    mutationFn: (id: string) => api.post<AdminUser>(`/users/${id}/unlock`, {}),
    onSuccess: () => {
      toast.success('Account unlocked', { description: 'Failed-login counter reset to zero.' });
      invalidate();
    },
    onError: (error) => toast.error('Unlock failed', { description: errorMessage(error) }),
  });

  const rows = users.data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Accounts &amp; access"
        description="Authorisation is permission-based: roles are bundles of permissions, and every endpoint declares the permissions it needs. The matrix below is generated from the code that enforces it, so it cannot drift from reality."
        actions={canWrite ? <CreateUserDialog /> : null}
      />

      <Tabs defaultValue="accounts">
        <TabsList>
          <TabsTrigger value="accounts" data-testid="tab-accounts">
            Accounts
          </TabsTrigger>
          <TabsTrigger value="matrix" data-testid="tab-matrix">
            Role matrix
          </TabsTrigger>
        </TabsList>

        <TabsContent value="accounts" className="space-y-4">
          <Card className="glass">
            <CardHeader className="gap-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <CardTitle>Accounts</CardTitle>
                  <CardDescription>
                    {formatInt(users.data?.meta.total ?? 0)} accounts
                  </CardDescription>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <form
                    className="flex items-end gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      setSearchQuery(search);
                    }}
                  >
                    <Input
                      value={search}
                      placeholder="Search name or email"
                      onChange={(e) => setSearch(e.target.value)}
                      className="w-52"
                      aria-label="Search accounts"
                    />
                    <Button type="submit" variant="outline" size="icon" aria-label="Search">
                      <Search />
                    </Button>
                  </form>
                  <Select value={roleFilter} onValueChange={setRoleFilter}>
                    <SelectTrigger className="w-44" data-testid="role-filter" aria-label="Role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All roles</SelectItem>
                      {ROLES.map((r) => (
                        <SelectItem key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger className="w-36" aria-label="Status">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All statuses</SelectItem>
                      <SelectItem value="ACTIVE">Active</SelectItem>
                      <SelectItem value="DISABLED">Disabled</SelectItem>
                      <SelectItem value="LOCKED">Locked</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-0">
              {users.isLoading ? (
                <LoadingPanel label="Loading accounts…" rows={6} />
              ) : users.error ? (
                <ErrorPanel error={users.error} onRetry={() => users.refetch()} />
              ) : rows.length === 0 ? (
                <EmptyState title="No accounts match" description="Adjust the filters." />
              ) : (
                <Table data-testid="users-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Email</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead className="text-right">Failed logins</TableHead>
                      <TableHead className="text-right">Last sign-in</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((u) => {
                      const isSelf = current?.id === u.id;
                      return (
                        <TableRow key={u.id}>
                          <TableCell className="font-medium">
                            {u.full_name}
                            {isSelf ? (
                              <Badge variant="outline" className="ml-2">
                                you
                              </Badge>
                            ) : null}
                          </TableCell>
                          <TableCell className="font-mono text-xs">{u.email}</TableCell>
                          <TableCell>
                            {canWrite && !isSelf ? (
                              <Select
                                value={u.roles[0]}
                                onValueChange={(v) =>
                                  update.mutate({ id: u.id, patch: { roles: [v] } })
                                }
                              >
                                <SelectTrigger className="h-8 w-40 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {ROLES.map((r) => (
                                    <SelectItem key={r} value={r}>
                                      {ROLE_LABELS[r]}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              <span className="text-xs">
                                {u.roles.map((r) => ROLE_LABELS[r as (typeof ROLES)[number]] ?? titleCase(r)).join(', ')}
                              </span>
                            )}
                          </TableCell>
                          <TableCell>
                            <Badge variant={STATUS_VARIANT[u.status] ?? 'outline'}>
                              {titleCase(u.status)}
                            </Badge>
                            {u.locked_until ? (
                              <p className="mt-1 text-[0.65rem] text-muted-foreground">
                                until {formatDateTime(u.locked_until)}
                              </p>
                            ) : null}
                          </TableCell>
                          <TableCell className="text-right font-mono">
                            {formatInt(u.failed_login_count)}
                          </TableCell>
                          <TableCell className="text-right text-xs text-muted-foreground">
                            {formatRelative(u.last_login_at)}
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center justify-end gap-2">
                              {canWrite && !isSelf ? (
                                <>
                                  <div className="flex items-center gap-1.5">
                                    <Switch
                                      id={`enabled-${u.id}`}
                                      checked={u.status === 'ACTIVE'}
                                      onCheckedChange={(on) =>
                                        update.mutate({
                                          id: u.id,
                                          patch: { status: on ? 'ACTIVE' : 'DISABLED' },
                                        })
                                      }
                                      aria-label="Enabled"
                                    />
                                    <Label
                                      htmlFor={`enabled-${u.id}`}
                                      className="text-[0.7rem] font-normal text-muted-foreground"
                                    >
                                      enabled
                                    </Label>
                                  </div>
                                  {u.locked_until || u.failed_login_count > 0 ? (
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => unlock.mutate(u.id)}
                                      disabled={unlock.isPending}
                                      data-testid="unlock-user"
                                    >
                                      <LockOpen />
                                      Unlock
                                    </Button>
                                  ) : null}
                                  <ResetPasswordDialog user={u} />
                                </>
                              ) : (
                                <span className="text-[0.7rem] text-muted-foreground">
                                  {isSelf ? 'manage from your profile menu' : 'read-only'}
                                </span>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="matrix" className="space-y-4">
          {roles.isLoading ? (
            <LoadingPanel label="Loading role matrix…" rows={6} />
          ) : roles.error ? (
            <ErrorPanel error={roles.error} onRetry={() => roles.refetch()} />
          ) : roles.data ? (
            <>
              <Card className="glass">
                <CardHeader>
                  <CardTitle>Role → permission matrix</CardTitle>
                  <CardDescription>{roles.data.note}</CardDescription>
                </CardHeader>
                <CardContent className="overflow-x-auto px-0">
                  <Table data-testid="role-matrix">
                    <TableHeader>
                      <TableRow>
                        <TableHead className="min-w-[16rem]">Permission</TableHead>
                        {roles.data.roles.map((r) => (
                          <TableHead key={r.code} className="text-center">
                            {r.name}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {roles.data.permissions.map((p) => (
                        <TableRow key={p.code}>
                          <TableCell>
                            <p className="font-mono text-xs">{p.code}</p>
                            <p className="text-[0.7rem] text-muted-foreground">{p.description}</p>
                          </TableCell>
                          {roles.data!.roles.map((r) => (
                            <TableCell key={r.code} className="text-center">
                              {r.permissions.includes(p.code) ? (
                                <ShieldCheck
                                  className="mx-auto size-4 text-risk-low"
                                  aria-label="granted"
                                />
                              ) : (
                                <span className="text-muted-foreground/40" aria-label="not granted">
                                  —
                                </span>
                              )}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {roles.data.roles.map((r) => (
                  <Card key={r.code} className="glass">
                    <CardHeader>
                      <CardTitle className="text-sm">{r.name}</CardTitle>
                      <CardDescription>{r.description}</CardDescription>
                    </CardHeader>
                    <CardContent>
                      <p className="label-muted mb-2">
                        {formatInt(r.permissions.length)} permissions
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {r.permissions.map((p) => (
                          <Badge key={p} variant="outline" className="font-mono text-[0.65rem]">
                            {p}
                          </Badge>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </>
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
