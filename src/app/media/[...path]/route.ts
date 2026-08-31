import { readFile, realpath } from 'node:fs/promises';
import { join, normalize, resolve, sep } from 'node:path';

import { serverEnv } from '@/server/env';

/**
 * Serves listing photos that the feed importers downloaded and re-hosted under
 * `MEDIA_ROOT_DIR` (default `<repo>/data/media`). Vendor terms (Entegral) forbid
 * hotlinking their images and `next.config.ts` denies all remote image hosts, so
 * every listing image is served from our own origin here.
 *
 * Paths are content-addressed (`/media/<feed>/<sha2>/<sha>.<ext>`), so responses
 * are immutable. Anything that isn't an allow-listed image file inside the root
 * is a 404 — never a 403, so the endpoint is not a file-existence oracle.
 */

export const dynamic = 'force-dynamic';

const CONTENT_TYPE: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  gif: 'image/gif',
};

const mediaRoot = (): string =>
  serverEnv.MEDIA_ROOT_DIR
    ? resolve(serverEnv.MEDIA_ROOT_DIR)
    : join(process.cwd(), 'data', 'media');

const notFound = (): Response => new Response('Not found', { status: 404 });

export async function GET(
  _request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path: segments } = await context.params;
  if (!Array.isArray(segments) || segments.length === 0) return notFound();

  const ext = segments[segments.length - 1]?.split('.').pop()?.toLowerCase() ?? '';
  const contentType = CONTENT_TYPE[ext];
  if (!contentType) return notFound();

  const root = mediaRoot();
  // normalize collapses "..", then the prefix check rejects any escape attempt
  // (absolute segments, encoded traversal) before we touch the filesystem.
  const candidate = normalize(join(root, ...segments));
  if (candidate !== root && !candidate.startsWith(root + sep)) return notFound();

  // Compare canonical paths so a symlinked root (e.g. /var -> /private/var on
  // macOS) still matches, while a symlink that escapes the tree does not.
  const realRoot = await realpath(root).catch(() => root);
  let real: string;
  try {
    real = await realpath(candidate);
  } catch {
    return notFound();
  }
  if (real !== realRoot && !real.startsWith(realRoot + sep)) return notFound();

  try {
    const data = await readFile(real);
    return new Response(new Uint8Array(data), {
      status: 200,
      headers: {
        'content-type': contentType,
        'cache-control': 'public, max-age=31536000, immutable',
        'content-length': String(data.byteLength),
      },
    });
  } catch {
    return notFound();
  }
}
