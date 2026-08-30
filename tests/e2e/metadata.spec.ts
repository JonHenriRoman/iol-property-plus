import { expect, test } from './fixtures';

const BASE = 'http://localhost:3100';

test('robots.txt allows /, disallows /api/, names the sitemap', async ({ request }) => {
  const body = await (await request.get('/robots.txt')).text();
  expect(body).toMatch(/Allow: \/$/m);
  expect(body).toMatch(/Disallow: \/api\/$/m);
  expect(body).toContain(`Sitemap: ${BASE}/sitemap.xml`);
});

test('sitemap.xml is valid XML with an absolute loc', async ({ request }) => {
  const body = await (await request.get('/sitemap.xml')).text();
  expect(body).toContain('<?xml');
  expect(body).toContain(`<loc>${BASE}</loc>`);
});

test('manifest.webmanifest is a standalone PWA manifest', async ({ request }) => {
  const res = await request.get('/manifest.webmanifest');
  const m = await res.json();
  expect(m.name).toBe('IOL Property Plus');
  expect(m.display).toBe('standalone');
  expect(m.icons.map((i: { src: string }) => i.src)).toEqual(['/icon', '/apple-icon']);
});

test('head carries canonical, Open Graph and Twitter tags', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href', BASE);
  await expect(page.locator('meta[property="og:title"]')).toHaveAttribute(
    'content',
    'IOL Property Plus',
  );
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
    'content',
    'summary_large_image',
  );
});
