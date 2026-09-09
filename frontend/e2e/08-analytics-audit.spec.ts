import { expect, storageStateFor, test } from './fixtures';

test.describe('Analytics and model evaluation', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('the model comparison reports measured metrics for every model', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByTestId('tab-models').click();

    const table = page.getByTestId('model-metrics');
    await expect(table).toBeVisible({ timeout: 30_000 });
    await expect(table).toContainText('Rule baseline');
    await expect(table).toContainText('LSTM');
    await expect(table).toContainText('Gradient boosting');

    // The rule baseline cannot produce calibrated probabilities, so its ROC AUC
    // and Brier score must read "n/a" rather than a fabricated number.
    const baselineRow = table.locator('tr', { hasText: 'Rule baseline' });
    await expect(baselineRow).toContainText('n/a');
  });

  test('the analytics window can be changed and correlations are qualified', async ({ page }) => {
    await page.goto('/analytics');
    await page.getByTestId('analytics-window').click();
    await page.getByRole('option', { name: 'Last 7 days' }).click();
    await expect(page.getByText(/readings analysed/i).first()).toBeVisible();
  });

});

test.describe('Audit trail', () => {
  test.use({ storageState: storageStateFor('admin') });

  test('the audit trail is filterable and declares itself append-only', async ({ page }) => {
    await page.goto('/audit');
    await expect(page.getByTestId('audit-table')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/append-only/i).first()).toBeVisible();

    await page.getByTestId('audit-table').locator('tbody tr').first().click();
    await expect(page.getByTestId('audit-detail')).toBeVisible();
    await expect(page.getByText(/cannot be edited or deleted/i)).toBeVisible();
  });

  test('sign-in and sign-out are themselves audited', async ({ page }) => {
    await page.goto('/audit');
    await expect(page.getByTestId('audit-table')).toContainText('admin@a4s.local', {
      timeout: 30_000,
    });
    await expect(page.getByTestId('audit-table')).toContainText(/auth\./i);
  });
});
