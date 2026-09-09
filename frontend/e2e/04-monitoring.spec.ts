import { expect, storageStateFor, test } from './fixtures';

test.describe('Monitoring, explainability and prediction', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('the dashboard renders the watchlist and live feed', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByTestId('watchlist')).toBeVisible();
    await expect(page.getByTestId('live-feed')).toBeVisible();
    // Provenance must be visible on the primary operational surface.
    await expect(page.getByTestId('prototype-banner')).toContainText('SIMULATED DATA');
  });

  test('the personnel roster lists soldiers and drills into a profile', async ({ page }) => {
    await page.goto('/personnel');
    await expect(page.getByTestId('personnel-table')).toBeVisible();
    await page.getByTestId('personnel-link').first().click();
    await expect(page).toHaveURL(/\/personnel\/[0-9a-f-]{36}/);
  });

  test('the WHY THIS RISK panel shows an exact factor decomposition', async ({ page }) => {
    await page.goto('/personnel');
    await page.getByTestId('personnel-link').first().click();
    const why = page.getByTestId('why-this-risk');
    await expect(why).toBeVisible({ timeout: 30_000 });
    // The panel must state the arithmetic, not just a headline score.
    await expect(why).toContainText('severity');
    await expect(why).toContainText('weight');
    await expect(why).toContainText('Recommended action');
  });

  test('a prediction can be run and reports its own explanation method', async ({ page }) => {
    await page.goto('/personnel');
    await page.getByTestId('personnel-link').first().click();

    const panel = page.getByTestId('prediction-panel');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('run-prediction').click();

    // Whatever the outcome, the panel must name the explainability technique
    // rather than implying SHAP-style attribution it does not compute.
    await expect(panel).toContainText(/gradient|permutation|occlusion|attention|coefficient/i, {
      timeout: 45_000,
    });
  });

  test('all models can be compared side by side for one individual', async ({ page }) => {
    await page.goto('/personnel');
    await page.getByTestId('personnel-link').first().click();
    await expect(page.getByTestId('prediction-panel')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('compare-models').click();
    await expect(page.getByTestId('prediction-panel')).toContainText(/lstm/i, { timeout: 45_000 });
  });

  test('the digital twin view loads for the same individual', async ({ page }) => {
    await page.goto('/personnel');
    await page.getByTestId('personnel-link').first().click();
    await page.waitForURL(/\/personnel\/[0-9a-f-]{36}$/);
    await page.goto(`${page.url()}/twin`);
    await expect(page.getByText(/digital twin/i).first()).toBeVisible({ timeout: 30_000 });
  });
});
