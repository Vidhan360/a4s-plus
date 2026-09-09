'use client';

import type { SessionUser, TokenPair } from './types';

/**
 * Session persistence.
 *
 * Tokens live in `localStorage`. That is a deliberate, documented trade-off
 * for a prototype whose backend is a stateless JWT API with no cookie/CSRF
 * layer: it keeps the demo runnable from any static host. A production
 * deployment should move the refresh token into an HttpOnly, SameSite=Strict
 * cookie — this module is the single seam where that change would happen.
 */

const ACCESS_KEY = 'a4s.access_token';
const REFRESH_KEY = 'a4s.refresh_token';
const USER_KEY = 'a4s.user';
const EXPIRY_KEY = 'a4s.access_expires_at';

export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  user: SessionUser;
  expiresAt: number;
}

function safeStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function saveSession(tokens: TokenPair, user: SessionUser): StoredSession {
  const expiresAt = Date.now() + tokens.expires_in * 1000;
  const storage = safeStorage();
  if (storage) {
    storage.setItem(ACCESS_KEY, tokens.access_token);
    storage.setItem(REFRESH_KEY, tokens.refresh_token);
    storage.setItem(USER_KEY, JSON.stringify(user));
    storage.setItem(EXPIRY_KEY, String(expiresAt));
  }
  return { accessToken: tokens.access_token, refreshToken: tokens.refresh_token, user, expiresAt };
}

export function readSession(): StoredSession | null {
  const storage = safeStorage();
  if (!storage) return null;
  const accessToken = storage.getItem(ACCESS_KEY);
  const refreshToken = storage.getItem(REFRESH_KEY);
  const rawUser = storage.getItem(USER_KEY);
  if (!accessToken || !refreshToken || !rawUser) return null;
  try {
    return {
      accessToken,
      refreshToken,
      user: JSON.parse(rawUser) as SessionUser,
      expiresAt: Number(storage.getItem(EXPIRY_KEY) ?? 0),
    };
  } catch {
    return null;
  }
}

export function clearSession(): void {
  const storage = safeStorage();
  if (!storage) return;
  [ACCESS_KEY, REFRESH_KEY, USER_KEY, EXPIRY_KEY].forEach((key) => storage.removeItem(key));
}

export function readAccessToken(): string | null {
  return safeStorage()?.getItem(ACCESS_KEY) ?? null;
}

export function readRefreshToken(): string | null {
  return safeStorage()?.getItem(REFRESH_KEY) ?? null;
}
