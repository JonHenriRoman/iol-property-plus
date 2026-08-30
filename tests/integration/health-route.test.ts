import { describe, expect, it } from 'vitest';

import { GET } from '../../src/app/api/health/route';

describe('GET /api/health', () => {
  it('returns 200 with { status: "ok" } and no external dependency', async () => {
    const res = GET();
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('application/json');
    await expect(res.json()).resolves.toEqual({ status: 'ok' });
  });
});
