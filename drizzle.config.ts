import { defineConfig } from 'drizzle-kit';

/**
 * drizzle-kit runs in plain Node, outside Next — it cannot import the
 * `server-only` env schema, so it reads DATABASE_URL directly with the same
 * localhost default. Introspection only (`pnpm db:pull`); the database schema
 * is owned in DataGrip and we never generate / migrate / push from here.
 */

const DATABASE_URL = process.env.DATABASE_URL ?? 'postgresql://localhost:5432/iol_property_plus';

export default defineConfig({
  dialect: 'postgresql',
  schema: './src/server/db/schema.ts',
  out: './src/server/db',
  schemaFilter: ['public'],
  casing: 'camelCase',
  dbCredentials: { url: DATABASE_URL },
});
