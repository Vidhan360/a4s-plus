import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearSession, readAccessToken, saveSession } from '@/lib/token-store';
import type { SessionUser, TokenPair } from '@/lib/types';

const USER: SessionUser = {
  id: 'u-1',
  email: 'commander@a4s.local',
  full_name: 'Cmdr Demo',
  status: 'ACTIVE',
  roles: ['COMMANDER'],
  permissions: ['dashboard:read'],
  last_login_at: null,
  password_changed_at: null,
};

function tokens(access: string, refresh: string): TokenPair {
  return { access_token: access, refresh_token: refresh, token_type: 'bearer', expires_in: 900 };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('api client', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    clearSession();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    clearSession();
  });

  it('attaches the bearer token and serialises query parameters', async () => {
    saveSession(tokens('access-1', 'refresh-1'), USER);
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], meta: { total: 0 } }));

    const { api } = await import('@/lib/api-client');
    await api.get('/alerts', { limit: 25, offset: 0, status: '', missing: null });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/alerts');
    expect(url).toContain('limit=25');
    expect(url).toContain('offset=0');
    // Empty strings and nulls must be dropped, not sent as `status=`.
    expect(url).not.toContain('status=');
    expect(url).not.toContain('missing=');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-1');
  });

  it('refreshes once on a 401 and replays the original request', async () => {
    saveSession(tokens('stale', 'refresh-1'), USER);

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'unauthorised' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ tokens: tokens('fresh', 'refresh-2'), user: USER }))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));

    const { api } = await import('@/lib/api-client');
    await expect(api.get('/dashboard')).resolves.toEqual({ ok: true });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toContain('/auth/refresh');
    // The rotated pair must be persisted, otherwise the next request replays a
    // consumed refresh token and the backend revokes the whole token family.
    expect(readAccessToken()).toBe('fresh');
  });

  it('coalesces concurrent refreshes into a single call', async () => {
    saveSession(tokens('stale', 'refresh-1'), USER);

    fetchMock.mockImplementation((url: string) => {
      if (url.includes('/auth/refresh')) {
        return Promise.resolve(jsonResponse({ tokens: tokens('fresh', 'refresh-2'), user: USER }));
      }
      const authorised = readAccessToken() === 'fresh';
      return Promise.resolve(
        authorised
          ? jsonResponse({ ok: true })
          : jsonResponse({ error: { code: 'unauthorised' } }, 401),
      );
    });

    const { api } = await import('@/lib/api-client');
    await Promise.all([api.get('/dashboard'), api.get('/alerts'), api.get('/personnel')]);

    const refreshCalls = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes('/auth/refresh'),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it('clears the session and notifies listeners when the refresh token is rejected', async () => {
    saveSession(tokens('stale', 'refresh-1'), USER);

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'unauthorised' } }, 401))
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'token_reuse' } }, 401));

    // `vi.resetModules()` runs between tests, so ApiError must be imported from
    // the same freshly-instantiated module graph as the client under test —
    // otherwise `instanceof` compares two distinct class objects.
    const { ApiError } = await import('@/lib/api-error');
    const { api, onSessionExpired } = await import('@/lib/api-client');
    const listener = vi.fn();
    onSessionExpired(listener);

    await expect(api.get('/dashboard')).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalled();
    expect(readAccessToken()).toBeNull();
  });

  it('surfaces the structured error envelope, including the request id', async () => {
    saveSession(tokens('access-1', 'refresh-1'), USER);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: 'forbidden',
            message: 'Missing permission alert:resolve',
            request_id: 'req-42',
          },
        }),
        { status: 403, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const { ApiError } = await import('@/lib/api-error');
    const { api } = await import('@/lib/api-client');
    const error = await api.get('/alerts').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as InstanceType<typeof ApiError>).status).toBe(403);
    expect((error as InstanceType<typeof ApiError>).code).toBe('forbidden');
    expect((error as InstanceType<typeof ApiError>).requestId).toBe('req-42');
    expect((error as InstanceType<typeof ApiError>).isForbidden).toBe(true);
  });

  it('does not attach a bearer token to anonymous sign-in requests', async () => {
    saveSession(tokens('access-1', 'refresh-1'), USER);
    fetchMock.mockResolvedValueOnce(jsonResponse({ tokens: tokens('a', 'b'), user: USER }));

    const { api } = await import('@/lib/api-client');
    await api.anonymousPost('/auth/login', { email: 'x@y.z', password: 'secret' });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('returns undefined for a 204 rather than throwing on an empty body', async () => {
    saveSession(tokens('access-1', 'refresh-1'), USER);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    const { api } = await import('@/lib/api-client');
    await expect(api.del('/anything')).resolves.toBeUndefined();
  });
});
