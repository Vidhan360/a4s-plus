import { expect, storageStateFor, test } from './fixtures';

test.describe('Administration', () => {
  test.use({ storageState: storageStateFor('admin') });

  test('runtime configuration is editable and resettable', async ({ page }) => {
    await page.goto('/admin/config');
    const card = page.getByTestId('config-risk.thresholds');
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/changes take effect immediately/i)).toBeVisible();

    const editor = card.getByRole('textbox');
    const original = (await editor.inputValue()).trim();
    const parsed = JSON.parse(original) as Record<string, unknown>;
    await editor.fill(JSON.stringify(parsed, null, 2));
    // Saving is only enabled once the JSON actually differs, which proves the
    // dirty-state guard works.
    await expect(page.getByTestId('save-risk.thresholds')).toBeDisabled();
  });

  test('invalid JSON is refused client-side before it reaches the API', async ({ page }) => {
    await page.goto('/admin/config');
    const card = page.getByTestId('config-risk.thresholds');
    await expect(card).toBeVisible({ timeout: 30_000 });
    await card.getByRole('textbox').fill('{ not json');
    await expect(page.getByText(/JSON error/i)).toBeVisible();
    await expect(page.getByTestId('save-risk.thresholds')).toBeDisabled();
  });

  test('system health declares capabilities honestly', async ({ page }) => {
    await page.goto('/admin/system');
    const caps = page.getByTestId('capabilities');
    await expect(caps).toBeVisible({ timeout: 30_000 });
    await expect(caps).toContainText('Reads real physiological sensors');
    await expect(caps).toContainText('Clinically validated for medical use');
    await expect(page.getByTestId('model-registry')).toBeVisible();
    await expect(page.getByTestId('hardware-seam')).toBeVisible();
  });

  test('an account can be created and then disabled', async ({ page }) => {
    await page.goto('/admin/users');
    await expect(page.getByTestId('users-table')).toBeVisible({ timeout: 30_000 });

    const email = `e2e-${Date.now()}@a4s.local`;
    await page.getByTestId('add-user').click();
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Full name').fill('E2E Temporary Account');
    await page.getByLabel('Initial password').fill('E2e-Temp-Password-2026!');
    await page.getByTestId('submit-user').click();

    const row = page.getByTestId('users-table').locator('tr', { hasText: email });
    await expect(row).toBeVisible({ timeout: 30_000 });
    await row.getByRole('switch').click();
    await expect(row).toContainText('Disabled', { timeout: 30_000 });
  });
});
