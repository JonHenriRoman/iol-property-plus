import { expect, test } from './fixtures';

test('GET /api/health returns { status: "ok" }', async ({ request }) => {
  const res = await request.get('/api/health');
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/json');
  expect(await res.json()).toEqual({ status: 'ok' });
});
