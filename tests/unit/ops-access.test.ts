import { afterEach, describe, expect, it, vi } from 'vitest';

const load = async () => {
  vi.resetModules();
  return import('@/server/ops-access');
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('isOpsUiEnabled', () => {
  it('is always on in local development', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', 'development');
    vi.stubEnv('OPS_UI_ENABLED', '');
    const { isOpsUiEnabled } = await load();
    expect(isOpsUiEnabled()).toBe(true);
  });

  it('is off in a deployed environment without the flag', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', 'production');
    vi.stubEnv('OPS_UI_ENABLED', '');
    const { isOpsUiEnabled } = await load();
    expect(isOpsUiEnabled()).toBe(false);
  });

  it('is on in a deployed environment when explicitly enabled', async () => {
    vi.stubEnv('NODE_ENV', 'test');
    vi.stubEnv('APP_ENV', 'staging');
    vi.stubEnv('OPS_UI_ENABLED', '1');
    const { isOpsUiEnabled } = await load();
    expect(isOpsUiEnabled()).toBe(true);
  });
});
