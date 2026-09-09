'use client';

import { ApiError } from './api-error';
import {
  clearSession,
  readAccessToken,
  readRefreshToken,
  readSession,
  saveSession,
} from './token-store';
import type { LoginResponse } from './types';

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/$/, '');

export const API_PREFIX = '/api/v1';

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Query;
  /** Skip the Authorization header (used by /auth/login and /auth/refresh). */
  anonymous?: boolean;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`${API_BASE_URL}${API_PREFIX}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined || value === '') continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Listeners notified when the session is lost, so the shell can redirect. */
const sessionListeners = new Set<() => void>();

export function onSessionExpired(listener: () => void): () => void {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

function announceSessionExpired() {
  sessionListeners.forEach((listener) => listener());
}

/**
 * A single in-flight refresh is shared by every concurrent 401 so a burst of
 * parallel queries cannot rotate the refresh token more than once — the
 * backend treats a replayed refresh token as reuse and revokes the family.
 */
let refreshInFlight: Promise<string | null> | null = null;

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `${response.status} ${response.statusText}`;
  let details: unknown = null;
  let requestId: string | null = response.headers.get('x-request-id');
  try {
    const payload = (await response.json()) as {
      error?: { code?: string; message?: string; details?: unknown; request_id?: string };
      detail?: unknown;
    };
    if (payload?.error) {
      code = payload.error.code ?? code;
      message = payload.error.message ?? message;
      details = payload.error.details ?? null;
      requestId = payload.error.request_id ?? requestId;
    } else if (payload?.detail) {
      message = typeof payload.detail === 'string' ? payload.detail : message;
      details = payload.detail;
    }
  } catch {
    /* non-JSON error body — keep the status line */
  }
  return new ApiError(response.status, code, message, details, requestId);
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = readRefreshToken();
  if (!refreshToken) return null;

  const response = await fetch(buildUrl('/auth/refresh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    clearSession();
    announceSessionExpired();
    return null;
  }

  const payload = (await response.json()) as LoginResponse;
  saveSession(payload.tokens, payload.user);
  return payload.tokens.access_token;
}

function ensureRefresh(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = refreshAccessToken().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function send<T>(path: string, options: RequestOptions, retry: boolean): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (!options.anonymous) {
    const token = readAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: 'no-store',
  });

  if (response.status === 401 && retry && !options.anonymous && readRefreshToken()) {
    const refreshed = await ensureRefresh();
    if (refreshed) return send<T>(path, options, false);
  }

  if (!response.ok) {
    const error = await parseError(response);
    if (error.status === 401 && !options.anonymous) {
      clearSession();
      announceSessionExpired();
    }
    throw error;
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) =>
    send<T>(path, { method: 'GET', query, signal }, true),
  post: <T>(path: string, body?: unknown, query?: Query) =>
    send<T>(path, { method: 'POST', body: body ?? {}, query }, true),
  patch: <T>(path: string, body?: unknown) => send<T>(path, { method: 'PATCH', body }, true),
  put: <T>(path: string, body?: unknown) => send<T>(path, { method: 'PUT', body }, true),
  del: <T>(path: string) => send<T>(path, { method: 'DELETE' }, true),
  /** Unauthenticated POST — only for sign-in and token refresh. */
  anonymousPost: <T>(path: string, body: unknown) =>
    send<T>(path, { method: 'POST', body, anonymous: true }, false),
};

/** Absolute WebSocket URL for the live event stream. */
export function websocketUrl(topics?: string[]): string | null {
  const session = readSession();
  if (!session) return null;
  const base = API_BASE_URL.replace(/^http/, 'ws');
  const url = new URL(`${base}${API_PREFIX}/ws`);
  url.searchParams.set('token', session.accessToken);
  if (topics?.length) url.searchParams.set('topics', topics.join(','));
  return url.toString();
}
