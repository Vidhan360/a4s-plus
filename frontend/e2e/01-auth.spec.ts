import { ACCOUNTS, expect, signIn, signOut, test } from './fixtures';

test.describe('Authentication and session handling', () => {
  test('an unauthenticated visitor is redirected to sign-in', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId('sign-in')).toBeVisible();
  });

  test('the honesty banner is present before anyone signs in', async ({ page }) => {
    await page.goto('/login');
    const banner = page.getByTestId('prototype-banner');
    await expect(banner).toContainText('SOFTWARE PROTOTYPE');
    await expect(banner).toContainText('SIMULATED DATA');
    await expect(banner).toContainText('NOT CLINICALLY VALIDATED');
  });

  test('wrong credentials are rejected with a visible error and no session', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Email address').fill(ACCOUNTS.viewer.email);
    await page.getByLabel('Password', { exact: true }).fill('definitely-not-the-password');
    await page.getByTestId('sign-in').click();
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('a commander can sign in, land on the dashboard and sign out again', async ({ page }) => {
    await signIn(page, 'commander');
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId('prototype-banner')).toBeVisible();
    await signOut(page);
    // After sign-out the protected route must not be reachable from history.
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });

  test('the session survives a full page reload', async ({ page }) => {
    await signIn(page, 'commander');
    await page.reload();
    await expect(page.getByTestId('user-menu')).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard/);
  });
});
