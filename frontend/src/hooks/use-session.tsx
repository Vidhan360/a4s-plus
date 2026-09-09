'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import * as React from 'react';

import { api, onSessionExpired } from '@/lib/api-client';
import { clearSession, readSession, saveSession } from '@/lib/token-store';
import type { LoginResponse, SessionUser } from '@/lib/types';

interface SessionContextValue {
  user: SessionUser | null;
  /** `true` until the stored session has been read on the client. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<SessionUser>;
  signOut: (allSessions?: boolean) => Promise<void>;
  can: (permission: string) => boolean;
  canAny: (...permissions: string[]) => boolean;
  hasRole: (role: string) => boolean;
  refreshUser: () => Promise<void>;
}

const SessionContext = React.createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<SessionUser | null>(null);
  const [loading, setLoading] = React.useState(true);
  const router = useRouter();
  const queryClient = useQueryClient();

  // Hydrate from storage once on the client. Server rendering must not see a
  // user, otherwise the markup would not match the first client render.
  React.useEffect(() => {
    const stored = readSession();
    setUser(stored?.user ?? null);
    setLoading(false);
  }, []);

  // The API client tells us when a refresh attempt failed for good.
  React.useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null);
        queryClient.clear();
        router.replace('/login?reason=expired');
      }),
    [queryClient, router],
  );

  const signIn = React.useCallback(
    async (email: string, password: string) => {
      const response = await api.anonymousPost<LoginResponse>('/auth/login', { email, password });
      saveSession(response.tokens, response.user);
      setUser(response.user);
      queryClient.clear();
      return response.user;
    },
    [queryClient],
  );

  const signOut = React.useCallback(
    async (allSessions = false) => {
      const stored = readSession();
      try {
        await api.post('/auth/logout', {
          refresh_token: stored?.refreshToken ?? null,
          all_sessions: allSessions,
        });
      } catch {
        // Signing out locally must succeed even if the server call fails.
      }
      clearSession();
      setUser(null);
      queryClient.clear();
      router.replace('/login');
    },
    [queryClient, router],
  );

  const refreshUser = React.useCallback(async () => {
    const fresh = await api.get<SessionUser>('/auth/me');
    setUser(fresh);
    const stored = readSession();
    if (stored) {
      saveSession(
        {
          access_token: stored.accessToken,
          refresh_token: stored.refreshToken,
          token_type: 'bearer',
          expires_in: Math.max(1, Math.round((stored.expiresAt - Date.now()) / 1000)),
        },
        fresh,
      );
    }
  }, []);

  const permissions = React.useMemo(() => new Set(user?.permissions ?? []), [user]);

  const value = React.useMemo<SessionContextValue>(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      refreshUser,
      can: (permission: string) => permissions.has(permission),
      canAny: (...wanted: string[]) => wanted.some((p) => permissions.has(p)),
      hasRole: (role: string) => Boolean(user?.roles.includes(role)),
    }),
    [user, loading, signIn, signOut, refreshUser, permissions],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = React.useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside <SessionProvider>.');
  return context;
}
