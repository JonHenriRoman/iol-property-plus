/**
 * Read-only connectivity + schema-match probe against the real database.
 *
 * Runs outside Next, so it cannot import the `server-only` client in
 * `src/server/db`; it builds its own single read-only connection from
 * DATABASE_URL and imports only the generated table definitions. Proves the
 * generated schema's column list matches the live table (0 rows is a pass — the
 * database is schema-only). `pnpm db:check`.
 */

import { drizzle } from 'drizzle-orm/postgres-js';
import postgres from 'postgres';

import { provinces } from '../src/server/db/schema';

const url = process.env.DATABASE_URL ?? 'postgresql://localhost:5432/iol_property_plus';
const sql = postgres(url, { max: 1, prepare: false });
const db = drizzle(sql);

try {
  const rows = await db.select().from(provinces).limit(1);
  console.log(`ok — provinces reachable via generated schema, rows returned: ${rows.length}`);
} finally {
  await sql.end();
}
