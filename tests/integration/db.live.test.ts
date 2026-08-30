import { readFileSync } from 'node:fs';
import postgres from 'postgres';
import { afterAll, describe, expect, it } from 'vitest';

/**
 * Opt-in. Runs only when TEST_DATABASE_URL points at a real Postgres:
 *
 *   TEST_DATABASE_URL=postgresql://localhost:5432/iol_property_plus pnpm test
 *
 * Skipped by default so `pnpm test` never touches a real database.
 */
const TEST_DATABASE_URL = process.env.TEST_DATABASE_URL;

const schemaTableNames = (): string[] => {
  const src = readFileSync(new URL('../../src/server/db/schema.ts', import.meta.url), 'utf8');
  return [...src.matchAll(/pgTable\("([^"]+)"/g)].map((m) => m[1]!).sort();
};

const suite = TEST_DATABASE_URL ? describe : describe.skip;

if (!TEST_DATABASE_URL) {
  console.info(
    'db.live.test.ts skipped — set TEST_DATABASE_URL to run it against a real database.',
  );
}

suite('live database schema match', () => {
  const sql = postgres(TEST_DATABASE_URL ?? '', { max: 1, prepare: false });

  afterAll(async () => {
    await sql.end();
  });

  it('has exactly the 24 tables the generated schema declares', async () => {
    const rows = await sql<{ table_name: string }[]>`
      select table_name from information_schema.tables
      where table_schema = 'public' and table_type = 'BASE TABLE'
      order by table_name
    `;
    const live = rows.map((r) => r.table_name);
    expect(live).toEqual(schemaTableNames());
    expect(live).toHaveLength(24);
  });
});
