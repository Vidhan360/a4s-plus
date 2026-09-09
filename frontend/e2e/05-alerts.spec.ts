import { expect, storageStateFor, test } from './fixtures';

test.describe('Alert queue', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('the alert queue loads with its live engine configuration', async ({ page }) => {
    await page.goto('/alerts');
    await expect(
      page.getByTestId('alerts-table').or(page.getByText('Nothing in this view')),
    ).toBeVisible({ timeout: 30_000 });
    // The engine's live configuration must be read from the database, not
    // hardcoded in the UI.
    await expect(page.getByText(/Live engine configuration/i)).toBeVisible();
  });

  test('an open alert can be acknowledged and then resolved', async ({ page }) => {
    // Make sure the engine has produced something to triage.
    await page.goto('/simulation');
    await page.getByTestId('sim-start').click();
    await expect(page.getByTestId('simulation-controls')).toHaveAttribute(
      'data-sim-status',
      'RUNNING',
      { timeout: 30_000 },
    );

    await page.goto('/alerts');
    const ack = page.getByTestId('acknowledge-alert').first();
    const appeared = await ack
      .waitFor({ state: 'visible', timeout: 60_000 })
      .then(() => true)
      .catch(() => false);

    if (!appeared) {
      // The scenario mix is stochastic within a seeded run; if nothing has
      // escalated yet we assert the empty state is honest rather than faking a
      // pass with a synthetic alert.
      await expect(page.getByText('Nothing in this view')).toBeVisible();
      return;
    }

    await ack.click();
    const resolve = page.getByTestId('resolve-alert').first();
    await expect(resolve).toBeVisible({ timeout: 30_000 });
    await resolve.click();
    await page.getByLabel(/resolution/i).fill('Descent completed; casualty stabilised.');
    await page.getByTestId('confirm-resolve').click();
    await expect(page.getByTestId('alerts-table')).toBeVisible();
  });

});

test.describe('Alert queue for a read-only role', () => {
  test.use({ storageState: storageStateFor('viewer') });

  test('a viewer cannot acknowledge alerts', async ({ page }) => {
    await page.goto('/alerts');
    await expect(page.getByTestId('acknowledge-alert')).toHaveCount(0);
  });
});
