import path from 'node:path';

import { expect, type Page, test as base } from '@playwright/test';

/** Where `auth.setup.ts` writes one storage state per demo role. */
export const STORAGE_DIR = path.join('e2e', '.auth');

export function storageStateFor(account: AccountName): string {
  return path.join(STORAGE_DIR, `${account}.json`);
}

/**
 * Demo credentials. These are the seeded accounts documented in the README;
 * they exist only in the local development database.
 */
export const ACCOUNTS = {
  admin: { email: 'admin@a4s.local', password: 'Adm1n-A4Splus-2026!' },
  commander: { email: 'commander@a4s.local', password: 'Cmdr-A4Splus-2026!' },
  medic: { email: 'medic@a4s.local', password: 'Medic-A4Splus-2026!' },
  operator: { email: 'operator@a4s.local', password: 'Oper-A4Splus-2026!' },
  viewer: { email: 'viewer@a4s.local', password: 'View-A4Splus-2026!' },
} as const;

export type AccountName = keyof typeof ACCOUNTS;

/** Backend origin, used when a test needs to talk to the API directly. */
export const API_BASE_URL = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';

/**
 * Interactive sign-in. Used by the authentication spec and the setup project;
 * feature specs reuse a saved storage state instead, so they do not hammer the
 * login rate limiter.
 */
export async function signIn(page: Page, account: AccountName = 'commander') {
  const { email, password } = ACCOUNTS[account];
  await page.goto('/login');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByTestId('sign-in').click();
  await expect(page.getByTestId('user-menu')).toBeVisible({ timeout: 30_000 });
}

export async function signOut(page: Page) {
  await page.getByTestId('user-menu').click();
  await page.getByTestId('sign-out').click();
  await expect(page).toHaveURL(/\/login/);
}

/** Navigate via the sidebar so the test also exercises the shell's routing. */
export async function navigate(page: Page, label: string, urlPattern: RegExp) {
  await page.getByRole('link', { name: label, exact: true }).first().click();
  await expect(page).toHaveURL(urlPattern);
}

export const test = base;
export { expect };
