import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('instrumentation register()', () => {
  it('is a no-op outside the nodejs runtime', async () => {
    vi.stubEnv('NEXT_RUNTIME', 'edge');
    vi.resetModules();
    const { register } = await import('../../src/instrumentation');
    await expect(register()).resolves.toBeUndefined();
  });

  it('is a no-op when NEXT_RUNTIME is unset', async () => {
    vi.stubEnv('NEXT_RUNTIME', undefined);
    vi.resetModules();
    const { register } = await import('../../src/instrumentation');
    await expect(register()).resolves.toBeUndefined();
  });

  it('validates the server env under the nodejs runtime without throwing on a valid env', async () => {
    vi.stubEnv('NEXT_RUNTIME', 'nodejs');
    vi.stubEnv('NODE_ENV', 'test');
    vi.resetModules();
    const { register } = await import('../../src/instrumentation');
    await expect(register()).resolves.toBeUndefined();
  });
});
