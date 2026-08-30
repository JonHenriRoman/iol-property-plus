import { PGlite } from '@electric-sql/pglite';
import { drizzle } from 'drizzle-orm/pglite';

import * as schema from '@/server/db/schema';

/**
 * Deterministic in-process Postgres for integration tests.
 *
 * Applies a hand-kept subset of the schema — the plain-typed reference tables
 * the tests actually touch. It is deliberately NOT the full 24-table dump:
 * `citext` / `tsvector` / generated columns are added here only when a feature
 * needs them. Full-schema fidelity is checked by the opt-in `db.live.test.ts`.
 *
 * The DDL below is kept byte-for-byte consistent with `src/server/db/schema.ts`.
 */
const SUBSET_DDL = `
  CREATE TABLE provinces (
    id serial PRIMARY KEY NOT NULL,
    name text NOT NULL,
    code text NOT NULL,
    country_code char(2) DEFAULT 'ZA' NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT uq_provinces_name UNIQUE (name, country_code),
    CONSTRAINT uq_provinces_code UNIQUE (code, country_code)
  );

  CREATE TABLE cities (
    id serial PRIMARY KEY NOT NULL,
    province_id integer NOT NULL REFERENCES provinces(id) ON DELETE RESTRICT,
    name text NOT NULL,
    slug text NOT NULL,
    latitude numeric(9, 6),
    longitude numeric(9, 6),
    created_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT uq_cities_province_name UNIQUE (province_id, name),
    CONSTRAINT uq_cities_province_slug UNIQUE (province_id, slug)
  );

  CREATE TABLE property_types (
    id serial PRIMARY KEY NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    category text DEFAULT 'Residential' NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    sort_order smallint DEFAULT 0 NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT uq_property_types_name UNIQUE (name),
    CONSTRAINT uq_property_types_slug UNIQUE (slug),
    CONSTRAINT property_types_category_check
      CHECK (category = ANY (ARRAY['Residential', 'Commercial', 'Agricultural', 'Land']))
  );
`;

type TestDb = ReturnType<typeof drizzle<typeof schema>> & { $client: PGlite };

const createTestDb = async (): Promise<TestDb> => {
  const client = new PGlite();
  await client.exec(SUBSET_DDL);
  const db = drizzle(client, { schema }) as TestDb;
  db.$client = client;
  return db;
};

const seedReferenceData = async (db: TestDb): Promise<void> => {
  await db.insert(schema.provinces).values([
    { name: 'Western Cape', code: 'WC' },
    { name: 'Gauteng', code: 'GP' },
  ]);
  await db.insert(schema.propertyTypes).values([
    { name: 'House', slug: 'house' },
    { name: 'Apartment', slug: 'apartment' },
  ]);
};

export { createTestDb, seedReferenceData };
export type { TestDb };
