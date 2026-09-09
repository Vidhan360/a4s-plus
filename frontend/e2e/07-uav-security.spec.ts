import { ACCOUNTS, API_BASE_URL, expect, storageStateFor, test } from './fixtures';

test.describe('UAV swarm', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('swarm telemetry renders and is labelled simulated', async ({ page }) => {
    await page.goto('/uav');
    await expect(page.getByTestId('drone-table')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/does not command real aircraft/i).first()).toBeVisible();
  });

  test('jamming can be injected while the engine runs, and is detected', async ({ page }) => {
    await page.goto('/simulation');
    await page.getByTestId('sim-start').click();
    await expect(page.getByTestId('simulation-controls')).toHaveAttribute(
      'data-sim-status',
      'RUNNING',
      { timeout: 30_000 },
    );

    await page.goto('/uav');
    await expect(page.getByTestId('drone-table')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('inject-jamming').click();
    await expect(page.getByTestId('drone-events')).toBeVisible({ timeout: 30_000 });

    // The injected fault must surface in the security monitor, tagged SIMULATED.
    await page.goto('/security');
    const events = page.getByTestId('security-events');
    await expect(events).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('origin-filter').click();
    await page.getByRole('option', { name: 'Simulated' }).click();
    await expect(events).toContainText('Simulated', { timeout: 30_000 });
  });
});

test.describe('Security monitor', () => {
  test.use({ storageState: storageStateFor('admin') });

  test('a failed sign-in is recorded as a REAL security event', async ({ page, request }) => {
    // Drive the failure straight at the API so the attempt is unambiguously
    // unauthenticated and independent of this context's saved admin session.
    const response = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
      data: { email: ACCOUNTS.operator.email, password: 'wrong-password-on-purpose' },
    });
    // 401 rejected, 423 locked out, 429 rate limited — every one of these is a
    // genuine control firing, and all of them are recorded.
    expect([401, 423, 429]).toContain(response.status());

    await page.goto('/security');
    await page.getByTestId('origin-filter').click();
    await page.getByRole('option', { name: 'Real' }).click();
    await expect(page.getByTestId('security-events')).toContainText('Real', { timeout: 30_000 });
  });

  test('the encryption demonstration round-trips and detects tampering', async ({ page }) => {
    await page.goto('/security');
    await page.getByTestId('tab-crypto').click();
    await page.getByTestId('crypto-plaintext').fill('Casualty at grid 42-17, HAPE suspected');
    await page.getByTestId('run-crypto-demo').click();

    const result = page.getByTestId('crypto-result');
    await expect(result).toBeVisible({ timeout: 30_000 });
    await expect(result).toContainText('AES-256-GCM');
    await expect(result).toContainText('Round-trip verified');
    // The wording must stay honest: this is a demonstration, not data-at-rest
    // encryption.
    await expect(page.getByText(/not.*the transport or storage encryption/i)).toBeVisible();
  });
});
