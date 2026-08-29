/**
 * Post-processes `src/server/db/schema.ts` after `drizzle-kit pull`.
 *
 * drizzle-kit cannot map the `citext` and `tsvector` column types and emits
 * `unknown("…")` with a `// TODO` comment, which does not type-check. This
 * rewrites those to the custom types in `./custom-types`. Idempotent; run by
 * `pnpm db:pull`.
 */

import { readFileSync, writeFileSync } from 'node:fs';

const SCHEMA_PATH = new URL('../src/server/db/schema.ts', import.meta.url);

const original = readFileSync(SCHEMA_PATH, 'utf8');
let out = original;

// Drop the "failed to parse" TODO lines.
out = out.replace(/^\s*\/\/ TODO: failed to parse database type '(?:citext|tsvector)'\n/gm, '');

// citext columns: `unknown("email")` → `citext("email")` (keeps any chained calls).
out = out.replace(/\bunknown\((["'][a-z_]*email["'])\)/g, 'citext($1)');

// tsvector generated column.
out = out.replace(/\bunknown\((["']search_vector["'])\)/g, 'tsvector($1)');

if (/\bunknown\(/.test(out)) {
  console.error('fix-generated-schema: unresolved unknown() columns remain:');
  for (const line of out.split('\n')) {
    if (line.includes('unknown(')) console.error(`  ${line.trim()}`);
  }
  process.exit(1);
}

// Add the custom-types import once, right after the drizzle-orm imports.
if (!out.includes('./custom-types')) {
  out = out.replace(
    /^(import \{ sql \} from "drizzle-orm"\n)/m,
    '$1import { citext, tsvector } from "./custom-types";\n',
  );
}

if (out === original) {
  console.log('fix-generated-schema: nothing to change');
} else {
  writeFileSync(SCHEMA_PATH, out);
  console.log('fix-generated-schema: rewrote citext/tsvector columns in schema.ts');
}
