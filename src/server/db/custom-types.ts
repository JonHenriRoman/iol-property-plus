import { customType } from 'drizzle-orm/pg-core';

/**
 * Postgres column types that `drizzle-kit pull` cannot map on its own.
 *
 * `citext` (from the citext extension) and `tsvector` both behave as strings for
 * read/write purposes; the database enforces their real semantics
 * (case-insensitive comparison, full-text indexing). `scripts/fix-generated-schema.mjs`
 * rewrites the generated `schema.ts` to use these after every `pnpm db:pull`.
 */

const citext = customType<{ data: string; driverData: string }>({
  dataType: () => 'citext',
});

const tsvector = customType<{ data: string; driverData: string }>({
  dataType: () => 'tsvector',
});

export { citext, tsvector };
