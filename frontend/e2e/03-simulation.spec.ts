import { expect, storageStateFor, test } from './fixtures';

test.describe('Simulation engine control', () => {
  test.use({ storageState: storageStateFor('commander') });

  test('a run can be started, produces telemetry, and can be stopped', async ({ page }) => {
    await page.goto('/simulation');

    const controls = page.getByTestId('simulation-controls');
    await expect(controls).toBeVisible();

    await page.getByTestId('sim-start').click();
    await expect(controls).toHaveAttribute('data-sim-status', 'RUNNING', { timeout: 30_000 });

    // Ticks must actually advance; a status flag alone would not prove the
    // engine is doing work.
    const ticks = page.getByTestId('sim-ticks');
    await expect(ticks).toBeVisible();
    const first = Number((await ticks.textContent())?.replace(/[^0-9]/g, '') ?? '0');
    await expect
      .poll(
        async () => Number((await ticks.textContent())?.replace(/[^0-9]/g, '') ?? '0'),
        { timeout: 45_000, message: 'simulation tick counter should increase' },
      )
      .toBeGreaterThan(first);

    await page.getByTestId('sim-stop').click();
    await expect(controls).toHaveAttribute('data-sim-status', 'STOPPED', { timeout: 30_000 });
  });

  test('the hardware seam declares the active data source honestly', async ({ page }) => {
    await page.goto('/simulation');
    const seam = page.getByTestId('data-source-panel');
    await expect(seam).toBeVisible();
    await expect(seam).toContainText(/simulat/i);
  });

  test('the live stream indicator reaches a connected state', async ({ page }) => {
    await page.goto('/dashboard');
    const indicator = page.getByTestId('stream-indicator');
    await expect(indicator).toBeVisible();
    await expect
      .poll(async () => indicator.getAttribute('data-status'), { timeout: 30_000 })
      .toBe('live');
  });
});
