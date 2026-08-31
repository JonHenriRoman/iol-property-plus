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

  it('treats a blank optional feed var as unset (cp .env.example .env.local)', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('FUSION_CLIENT_ID', '');
    vi.stubEnv('FUSION_API_BASE_URL', '');
    vi.stubEnv('PROPCTRL_API_BASE_URL', '');
    vi.stubEnv('ALLSA_FEED_BASE_URL', '');
    const { serverEnv } = await loadEnv();
    expect(serverEnv.FUSION_CLIENT_ID).toBeUndefined();
    expect(serverEnv.FUSION_API_BASE_URL).toBeUndefined();
    expect(serverEnv.PROPCTRL_API_BASE_URL).toBeUndefined();
    expect(serverEnv.ALLSA_FEED_BASE_URL).toBeUndefined();
  });

  it('still validates a non-empty optional feed URL', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('FUSION_API_BASE_URL', 'not-a-url');
    await expect(loadEnv()).rejects.toThrow(/Invalid server environment/);
  });
});
