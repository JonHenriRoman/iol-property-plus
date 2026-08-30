import { expect, test } from './fixtures';

test('unknown path serves the 404 page with a working home link', async ({ page }) => {
  const res = await page.goto('/no-such-page');
  expect(res?.status()).toBe(404);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Page not found');

  await page.getByRole('link', { name: 'Return home' }).click();
  await expect(page).toHaveURL('http://localhost:3100/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('IOL Property Plus');
});
