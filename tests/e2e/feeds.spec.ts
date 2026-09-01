import { expect, test } from './fixtures';

test.describe('feed operations UI', () => {
  test('the add-feed form shows vendor-specific fields and switches with the vendor', async ({
    page,
  }) => {
    await page.goto('/ops/feeds/new');

    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Add feed');

    // AllSA is first: it asks for an Agency ID.
    const vendor = page.getByLabel('Vendor');
    await expect(vendor).toHaveValue('allsa');
    await expect(page.getByLabel('Agency ID')).toBeVisible();

    // Switching to RT3 swaps the identity fields.
    await vendor.selectOption('rt3');
    await expect(page.getByLabel('Agency ID')).toHaveCount(0);
    await expect(page.getByLabel('Provinces')).toBeVisible();

    // The code field is prefilled with the vendor convention.
    await expect(page.getByLabel('Feed code')).toHaveValue('rt3-');
  });

  test('client-side required fields block an empty submit', async ({ page }) => {
    await page.goto('/ops/feeds/new');
    await page.getByRole('button', { name: 'Create feed' }).click();
    // Still on the form — nothing navigated.
    await expect(page).toHaveURL(/\/ops\/feeds\/new$/);
  });
});
