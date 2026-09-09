'use client';

import { useMutation } from '@tanstack/react-query';
import { KeyRound, LogOut, ShieldCheck } from 'lucide-react';
import * as React from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { ApiError, errorMessage } from '@/lib/api-error';
import { ROLE_LABELS, type Role } from '@/lib/constants';
import { formatRelative } from '@/lib/format';

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join('');
}

function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [current, setCurrent] = React.useState('');
  const [next, setNext] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [fieldError, setFieldError] = React.useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post('/auth/change-password', { current_password: current, new_password: next }),
    onSuccess: () => {
      toast.success('Password changed', {
        description: 'Every other session for this account was revoked.',
      });
      onOpenChange(false);
      setCurrent('');
      setNext('');
      setConfirm('');
    },
    onError: (error) => {
      const detail =
        error instanceof ApiError ? Object.values(error.fieldErrors)[0] : undefined;
      setFieldError(detail ?? errorMessage(error));
    },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setFieldError(null);
    if (next !== confirm) {
      setFieldError('The two new-password fields do not match.');
      return;
    }
    mutation.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>
            Passwords are hashed with Argon2id. Changing it revokes every other refresh token
            issued to this account.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              value={next}
              onChange={(event) => setNext(event.target.value)}
              required
            />
            <p className="text-[0.68rem] text-muted-foreground">
              At least 12 characters, mixing upper case, lower case, a digit and a symbol.
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-password">Confirm new password</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              required
            />
          </div>
          {fieldError ? <p className="text-xs text-destructive">{fieldError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              Change password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function UserMenu() {
  const { user, signOut } = useSession();
  const [passwordOpen, setPasswordOpen] = React.useState(false);

  if (!user) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="h-9 gap-2 px-2"
            aria-label="Account menu"
            data-testid="user-menu"
          >
            <span className="grid size-6 place-items-center rounded-full bg-gradient-to-br from-primary/80 to-accent/80 text-[0.65rem] font-bold text-primary-foreground">
              {initials(user.full_name)}
            </span>
            <span className="hidden max-w-[130px] truncate text-xs font-medium sm:block">
              {user.full_name}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-[290px]">
          <DropdownMenuLabel className="space-y-1 py-2">
            <p className="text-sm">{user.full_name}</p>
            <p className="text-xs font-normal text-muted-foreground">{user.email}</p>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="space-y-2 px-2 py-2">
            <p className="label-muted">Roles</p>
            <div className="flex flex-wrap gap-1.5">
              {user.roles.map((role) => (
                <span
                  key={role}
                  className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[0.65rem] font-semibold text-primary"
                >
                  {ROLE_LABELS[role as Role] ?? role}
                </span>
              ))}
            </div>
            <p className="flex items-center gap-1.5 text-[0.68rem] text-muted-foreground">
              <ShieldCheck className="size-3" />
              {user.permissions.length} permissions · last sign-in{' '}
              {formatRelative(user.last_login_at)}
            </p>
          </div>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setPasswordOpen(true)}>
            <KeyRound />
            Change password
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void signOut(false)} data-testid="sign-out">
            <LogOut />
            Sign out
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => void signOut(true)}>
            <LogOut />
            Sign out of all sessions
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ChangePasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} />
    </>
  );
}
