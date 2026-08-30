import { expect, test } from './fixtures';

for (const path of ['/icon', '/apple-icon', '/opengraph-image']) {
  test(`${path} returns an image`, async ({ request }) => {
    const res = await request.get(path);
    expect(res.status()).toBe(200);
    expect(res.headers()['content-type']).toMatch(/^image\//);
  });
}
