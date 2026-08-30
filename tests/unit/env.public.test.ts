import { afterEach, describe, expect, it, vi } from 'vitest';

const loadEnv = async () => {
  vi.resetModules();
  return import('@/config/env');
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('publicEnvSchema', () => {
  it('defaults NEXT_PUBLIC_SITE_URL to localhost when unset', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', undefined);
    const { publicEnv } = await loadEnv();
    expect(publicEnv.NEXT_PUBLIC_SITE_URL).toBe('http://localhost:3000');
  });

  it('accepts a valid URL', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'https://propertyplus.example.co.za');
    const { publicEnv } = await loadEnv();
    expect(publicEnv.NEXT_PUBLIC_SITE_URL).toBe('https://propertyplus.example.co.za');
  });

  it('throws a prettified error on a non-URL value', async () => {
    vi.stubEnv('NEXT_PUBLIC_SITE_URL', 'not-a-url');
    await expect(loadEnv()).rejects.toThrow(/Invalid public environment/);
  });
});
