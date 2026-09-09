'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Clock, Eye, EyeOff, Lock, ShieldCheck } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import * as React from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Brand } from '@/components/layout/brand';
import { PrototypeBanner } from '@/components/layout/prototype-banner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSession } from '@/hooks/use-session';
import { api } from '@/lib/api-client';
import { ApiError } from '@/lib/api-error';
import { APP_LONG_NAME, DISCLAIMERS, TAGLINE } from '@/lib/constants';
import { qk } from '@/lib/query-keys';
import type { ServiceMeta } from '@/lib/types';

const schema = z.object({
  email: z.string().min(1, 'Enter your email address.').email('That is not a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
});

type FormValues = z.infer<typeof schema>;

const DEMO_ACCOUNTS = [
  { role: 'Administrator', email: 'admin@a4s.local', can: 'Everything, including users and config' },
  { role: 'Commander', email: 'commander@a4s.local', can: 'Operations, routing, security drills' },
  { role: 'Medical officer', email: 'medic@a4s.local', can: 'Vitals, risk, alerts, digital twins' },
  { role: 'Operator', email: 'operator@a4s.local', can: 'Simulation, UAV swarm, routing' },
  { role: 'Viewer', email: 'viewer@a4s.local', can: 'Read-only dashboard and roster' },
];

function LoginView() {
  const { signIn, user, loading } = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [showPassword, setShowPassword] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const [lockedUntil, setLockedUntil] = React.useState<string | null>(null);

  const reason = searchParams.get('reason');

  const { data: meta } = useQuery({
    queryKey: qk.meta,
    queryFn: () => api.get<ServiceMeta>('/meta'),
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
  });

  React.useEffect(() => {
    if (!loading && user) router.replace('/dashboard');
  }, [loading, user, router]);

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    setLockedUntil(null);
    try {
      await signIn(values.email.trim(), values.password);
      router.replace('/dashboard');
    } catch (error) {
      if (error instanceof ApiError && error.status === 423) {
        setLockedUntil(error.message);
        return;
      }
      if (error instanceof ApiError && error.status === 429) {
        setFormError('Too many sign-in attempts from this address. Wait a minute and try again.');
        return;
      }
      setFormError(
        error instanceof ApiError && error.status === 401
          ? 'Those credentials were rejected. Check the address and password and try again.'
          : error instanceof Error
            ? error.message
            : 'Sign-in failed.',
      );
    }
  };

  return (
    <div className="flex min-h-screen flex-col">
      <PrototypeBanner />
      <div className="grid flex-1 lg:grid-cols-[1.05fr_1fr]">
        {/* Narrative panel */}
        <section className="relative hidden flex-col justify-between overflow-hidden border-r border-white/[0.06] p-10 lg:flex">
          <div className="pointer-events-none absolute inset-0 bg-grid-faint [background-size:44px_44px] opacity-40" />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-radial-fade" />
          <div className="relative">
            <Brand />
          </div>
          <div className="relative max-w-xl space-y-6">
            <div className="space-y-3">
              <p className="label-muted">{APP_LONG_NAME}</p>
              <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight">
                {TAGLINE}
              </h1>
              <p className="text-sm leading-relaxed text-muted-foreground">
                A4S+ watches a simulated high-altitude deployment: it scores physiological risk from
                telemetry, forecasts deterioration 30 simulated minutes ahead with a trained LSTM,
                explains every score, and plans a hazard-aware evacuation route with A*.
              </p>
            </div>
            <dl className="grid gap-4 sm:grid-cols-3">
              {[
                { term: 'Detection', detail: 'Transparent, weighted rule engine over 9 vitals' },
                { term: 'Prediction', detail: 'PyTorch LSTM trained on synthetic subjects' },
                { term: 'Prevention', detail: 'Alerting, safe routing and UAV tasking' },
              ].map((entry) => (
                <div key={entry.term} className="glass p-4">
                  <dt className="text-xs font-semibold text-primary">{entry.term}</dt>
                  <dd className="mt-1 text-[0.7rem] leading-relaxed text-muted-foreground">
                    {entry.detail}
                  </dd>
                </div>
              ))}
            </dl>
            <Alert variant="warning">
              <ShieldCheck />
              <AlertTitle>Read this before the demo</AlertTitle>
              <AlertDescription>{DISCLAIMERS.long}</AlertDescription>
            </Alert>
          </div>
          <p className="relative text-[0.68rem] text-muted-foreground">
            {meta ? (
              <>
                {meta.name} v{meta.version} · {meta.prototype_status} · {meta.data_mode} ·{' '}
                {meta.validation_status}
              </>
            ) : (
              'Backend metadata unavailable — the API may not be running yet.'
            )}
          </p>
        </section>

        {/* Sign-in panel */}
        <section className="flex items-center justify-center px-5 py-12">
          <div className="w-full max-w-[420px] space-y-6">
            <div className="space-y-2 lg:hidden">
              <Brand />
            </div>

            <div className="space-y-1.5">
              <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
              <p className="text-xs text-muted-foreground">
                Access is permission-based. What you can see and do depends on the roles attached to
                your account.
              </p>
            </div>

            {reason === 'expired' ? (
              <Alert variant="warning">
                <Clock />
                <AlertTitle>Session expired</AlertTitle>
                <AlertDescription>
                  Your refresh token was rejected or had already been used. Sign in again.
                </AlertDescription>
              </Alert>
            ) : null}

            {lockedUntil ? (
              <Alert variant="destructive" data-testid="lockout-alert">
                <Lock />
                <AlertTitle>Account temporarily locked</AlertTitle>
                <AlertDescription>{lockedUntil}</AlertDescription>
              </Alert>
            ) : null}

            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="email">Email address</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="username"
                  placeholder="commander@a4s.local"
                  aria-invalid={Boolean(form.formState.errors.email)}
                  {...form.register('email')}
                />
                {form.formState.errors.email ? (
                  <p className="text-xs text-destructive" role="alert">
                    {form.formState.errors.email.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    className="pr-10"
                    aria-invalid={Boolean(form.formState.errors.password)}
                    {...form.register('password')}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((value) => !value)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
                {form.formState.errors.password ? (
                  <p className="text-xs text-destructive" role="alert">
                    {form.formState.errors.password.message}
                  </p>
                ) : null}
              </div>

              {formError ? (
                <p className="text-xs text-destructive" role="alert" data-testid="login-error">
                  {formError}
                </p>
              ) : null}

              <Button
                type="submit"
                className="w-full"
                size="lg"
                loading={form.formState.isSubmitting}
                data-testid="sign-in"
              >
                Sign in
                <ArrowRight />
              </Button>
            </form>

            <div className="glass space-y-3 p-4">
              <p className="label-muted">Demo accounts</p>
              <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
                Passwords are set from environment variables when the database is seeded, so they
                are intentionally not printed here. See <span className="font-mono">README.md</span>{' '}
                for the seeded values.
              </p>
              <ul className="space-y-1.5">
                {DEMO_ACCOUNTS.map((account) => (
                  <li key={account.email} className="flex items-baseline justify-between gap-3">
                    <button
                      type="button"
                      className="font-mono text-[0.7rem] text-primary hover:underline"
                      onClick={() => form.setValue('email', account.email)}
                    >
                      {account.email}
                    </button>
                    <span className="text-right text-[0.65rem] text-muted-foreground">
                      {account.role}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <p className="text-[0.68rem] leading-relaxed text-muted-foreground">
              Sign-in attempts are rate limited, failures are counted, and repeated failures lock
              the account for a configured window. Every attempt is written to the append-only audit
              log.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

/**
 * `useSearchParams` opts the subtree into client-side rendering, so the page
 * wraps it in a Suspense boundary. Without this, `next build` refuses to
 * prerender /login at all.
 */
export default function LoginPage() {
  return (
    <React.Suspense fallback={<div className="min-h-dvh bg-background" aria-busy="true" />}>
      <LoginView />
    </React.Suspense>
  );
}
