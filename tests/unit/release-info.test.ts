import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('getReleaseInfo', () => {
  it('reads commitSha and environment from the server env', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', 'staging');
    vi.stubEnv('GIT_COMMIT_SHA', 'abc1234');
    vi.resetModules();
    const { getReleaseInfo } = await import('@/server/release-info');
    expect(getReleaseInfo()).toEqual({ commitSha: 'abc1234', environment: 'staging' });
  });

  it('falls back to the schema defaults', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', undefined);
    vi.stubEnv('GIT_COMMIT_SHA', undefined);
    vi.resetModules();
    const { getReleaseInfo } = await import('@/server/release-info');
    expect(getReleaseInfo()).toEqual({ commitSha: 'dev', environment: 'development' });
  });
});
