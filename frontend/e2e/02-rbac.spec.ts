import { expect, storageStateFor, test } from './fixtures';

test.describe('Viewer scope', () => {
  test.use({ storageState: storageStateFor('viewer') });

  test('a viewer sees read-only surfaces and no administration section', async ({ page }) => {
    await page.goto('/dashboard');
    // Navigation is filtered by permission, so the admin section must be absent
    // rather than present-but-broken.
    await expect(page.getByRole('link', { name: 'Users & roles', exact: true })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Runtime config', exact: true })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Command dashboard', exact: true })).toBeVisible();
  });

  test('a viewer that deep-links into an admin page is told it is out of scope', async ({
    page,
  }) => {
    await page.goto('/admin/users');
    // The API answers 403 and the panel renders the RBAC explanation instead of
    // a generic failure.
    await expect(page.getByText('Your role does not include this view').first()).toBeVisible();
  });
});

test.describe('Medical officer scope', () => {
  test.use({ storageState: storageStateFor('medic') });

  test('a medical officer has no security monitor entry', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('link', { name: 'Security monitor', exact: true })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Personnel', exact: true })).toBeVisible();
  });
});

test.describe('Operator scope', () => {
  test.use({ storageState: storageStateFor('operator') });

  test('an operator reaches the security monitor but not account administration', async ({
    page,
  }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('link', { name: 'Security monitor', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Users & roles', exact: true })).toHaveCount(0);
  });
});

test.describe('Administrator scope', () => {
  test.use({ storageState: storageStateFor('admin') });

  test('an admin can manage accounts', async ({ page }) => {
    await page.goto('/dashboard');
    await page.getByRole('link', { name: 'Users & roles', exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/users/);
    await expect(page.getByTestId('users-table')).toBeVisible();
  });

  test('the role matrix is rendered from the enforced permission set', async ({ page }) => {
    await page.goto('/admin/users');
    await page.getByTestId('tab-matrix').click();
    const matrix = page.getByTestId('role-matrix');
    await expect(matrix).toBeVisible();
    await expect(matrix).toContainText('security:simulate');
    await expect(matrix).toContainText('alert:ack');
  });
});
