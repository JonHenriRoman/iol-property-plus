import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let root: string;

const loadRoute = async () => {
  vi.resetModules();
  return import('../../src/app/media/[...path]/route');
};

const call = async (segments: string[]) => {
  const { GET } = await loadRoute();
  return GET(new Request('http://localhost/media'), {
    params: Promise.resolve({ path: segments }),
  });
};

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'media-route-'));
  mkdirSync(join(root, 'entegral', 'ab'), { recursive: true });
  writeFileSync(join(root, 'entegral', 'ab', 'abc123.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  vi.stubEnv('NODE_ENV', 'test');
  vi.stubEnv('MEDIA_ROOT_DIR', root);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /media/[...path]', () => {
  it('serves a stored image with an immutable cache header', async () => {
    const res = await call(['entegral', 'ab', 'abc123.png']);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('image/png');
    expect(res.headers.get('cache-control')).toContain('immutable');
    expect((await res.arrayBuffer()).byteLength).toBe(4);
  });

  it('404s a path traversal attempt', async () => {
    const res = await call(['..', '..', '..', 'etc', 'passwd']);
    expect(res.status).toBe(404);
  });

  it('404s an absolute path segment', async () => {
    const res = await call(['/etc/hosts']);
    expect(res.status).toBe(404);
  });

  it('404s a non-image extension', async () => {
    writeFileSync(join(root, 'entegral', 'ab', 'secret.txt'), 'nope');
    const res = await call(['entegral', 'ab', 'secret.txt']);
    expect(res.status).toBe(404);
  });

  it('404s a missing file', async () => {
    const res = await call(['entegral', 'ab', 'deadbeef.png']);
    expect(res.status).toBe(404);
  });
});
