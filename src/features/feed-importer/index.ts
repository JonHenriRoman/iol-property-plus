/**
 * Public surface of the feed-importer feature.
 *
 * Only framework-neutral pieces are re-exported here. Server code
 * (`./server/queries`, `./server/actions`) and client components
 * (`./components/*`) are imported directly by the route files that use them, to
 * keep the `server-only` boundary clean. The vendor registry lives in
 * `@/lib/feed-vendors` (framework-neutral, shared with `src/server`).
 */
export { parseFeedForm } from './schema';
export type { ParsedFeed, ParseResult } from './schema';
