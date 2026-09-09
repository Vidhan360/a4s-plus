import { expect, storageStateFor, test } from './fixtures';

test.describe('Terrain and safe routing', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('the terrain grid renders and is labelled synthetic', async ({ page }) => {
    await page.goto('/terrain');
    await expect(page.getByTestId('terrain-canvas')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/synthetic terrain/i).first()).toBeVisible();
  });

  test('a hazard layer can be selected', async ({ page }) => {
    await page.goto('/terrain');
    await expect(page.getByTestId('terrain-canvas')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('terrain-layer').click();
    await page.getByRole('option', { name: 'Avalanche risk' }).click();
    await expect(page.getByText('Avalanche risk').first()).toBeVisible();
  });

  test('a route can be planned and explains why it was chosen', async ({ page }) => {
    await page.goto('/routes');
    await expect(page.getByTestId('terrain-canvas')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('plan-route').click();
    await expect(page.getByTestId('route-explanation')).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId('route-history')).toBeVisible();
  });

  test("A*'s optimality is verified against Dijkstra rather than asserted", async ({ page }) => {
    await page.goto('/routes');
    await expect(page.getByTestId('terrain-canvas')).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('verify-optimality').click();
    const result = page.getByTestId('optimality-result');
    await expect(result).toBeVisible({ timeout: 45_000 });
    await expect(result).toContainText('Dijkstra cost');
  });
});
