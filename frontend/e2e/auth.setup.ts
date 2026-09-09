import fs from 'node:fs';
import path from 'node:path';

import { expect, type Page, test as setup } from '@playwright/test';

import { ACCOUNTS, type AccountName, STORAGE_DIR, storageStateFor } from './fixtures';

/**
 * Signs in once per demo role and saves the resulting browser storage.
 *
 * The backend deliberately locks accounts after repeated failures and rate
 * limits `/auth/login` to 10 requests per minute per client. Signing in inside
 * every test would exercise those controls instead of the feature under test,
 * so each role authenticates once here and the specs reuse the saved state.
 */
async function signInWithBackoff(page: Page, account: AccountName) {
  const { email, password } = ACCOUNTS[account];

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.goto('/login');
    await page.getByLabel('Email address').fill(email);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByTestId('sign-in').click();

    const menu = page.getByTestId('user-menu');
    // A 429 renders as the inline form error; a 423 renders as the lockout alert.
    const rejected = page.getByTestId('login-error').or(page.getByTestId('lockout-alert'));
    await expect(menu.or(rejected)).toBeVisible({ timeout: 30_000 });
    if (await menu.isVisible()) return;

    // Rate limiting is a real control, not a bug. Wait out the window instead
    // of weakening the limit for the sake of the test suite.
    // eslint-disable-next-line no-console
    console.warn(`sign-in for ${account} was throttled; waiting out the window (attempt ${attempt})`);
    await page.waitForTimeout(35_000);
  }

  throw new Error(`Could not authenticate as ${account} after three attempts.`);
}

for (const name of Object.keys(ACCOUNTS) as AccountName[]) {
  setup(`authenticate as ${name}`, async ({ page }) => {
    setup.setTimeout(180_000);
    fs.mkdirSync(STORAGE_DIR, { recursive: true });
    await signInWithBackoff(page, name);
    await page.context().storageState({ path: path.resolve(storageStateFor(name)) });
  });
}
