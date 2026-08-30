import { afterEach, describe, expect, it, vi } from 'vitest';

const loadEnv = async () => {
  vi.resetModules();
  return import('@/server/env');
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('serverEnvSchema', () => {
  it('applies defaults for APP_ENV, GIT_COMMIT_SHA and DATABASE_URL', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', undefined);
    vi.stubEnv('GIT_COMMIT_SHA', undefined);
    vi.stubEnv('DATABASE_URL', undefined);
    const { serverEnv } = await loadEnv();
    expect(serverEnv.APP_ENV).toBe('development');
    expect(serverEnv.GIT_COMMIT_SHA).toBe('dev');
    expect(serverEnv.DATABASE_URL).toBe('postgresql://localhost:5432/iol_property_plus');
  });

  it('accepts postgres:// and postgresql:// DATABASE_URL schemes', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    for (const url of [
      'postgres://u:p@host:5432/db',
      'postgresql://localhost:5432/iol_property_plus',
    ]) {
      vi.stubEnv('DATABASE_URL', url);
      const { serverEnv } = await loadEnv();
      expect(serverEnv.DATABASE_URL).toBe(url);
    }
  });

  it('rejects a non-postgres DATABASE_URL scheme', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('DATABASE_URL', 'http://localhost:5432/db');
    await expect(loadEnv()).rejects.toThrow(/Invalid server environment/);
  });

  it('rejects an APP_ENV outside the enum', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', 'qa');
    await expect(loadEnv()).rejects.toThrow(/APP_ENV/);
  });
});
