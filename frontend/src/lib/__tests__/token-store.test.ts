import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearSession,
  readAccessToken,
  readRefreshToken,
  readSession,
  saveSession,
} from '@/lib/token-store';
import type { SessionUser, TokenPair } from '@/lib/types';

const USER: SessionUser = {
  id: 'u-1',
  email: 'admin@a4s.local',
  full_name: 'Admin Demo',
  status: 'ACTIVE',
  roles: ['ADMIN'],
  permissions: ['user:write'],
  last_login_at: null,
  password_changed_at: null,
};

const TOKENS: TokenPair = {
  access_token: 'access',
  refresh_token: 'refresh',
  token_type: 'bearer',
  expires_in: 900,
};

describe('token store', () => {
  beforeEach(() => clearSession());

  it('round-trips a session', () => {
    saveSession(TOKENS, USER);
    const session = readSession();
    expect(session?.accessToken).toBe('access');
    expect(session?.refreshToken).toBe('refresh');
    expect(session?.user.email).toBe('admin@a4s.local');
    expect(session?.expiresAt).toBeGreaterThan(Date.now());
  });

  it('clears every key on sign-out', () => {
    saveSession(TOKENS, USER);
    clearSession();
    expect(readSession()).toBeNull();
    expect(readAccessToken()).toBeNull();
    expect(readRefreshToken()).toBeNull();
  });

  it('treats corrupt stored state as no session instead of crashing the shell', () => {
    saveSession(TOKENS, USER);
    window.localStorage.setItem('a4s.user', '{not json');
    expect(readSession()).toBeNull();
  });
});
