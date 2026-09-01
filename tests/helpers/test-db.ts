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

  CREATE TYPE feed_format AS ENUM ('XML', 'JSON', 'CSV', 'API');
  CREATE TYPE import_job_status AS ENUM ('Pending', 'Running', 'Success', 'PartialSuccess', 'Failed');

  CREATE TABLE feed_sources (
    id serial PRIMARY KEY NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    vendor_name text NOT NULL,
    format feed_format DEFAULT 'XML' NOT NULL,
    base_url text,
    auth_config jsonb DEFAULT '{}' NOT NULL,
    ttl_minutes integer DEFAULT 1440 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    CONSTRAINT uq_feed_sources_code UNIQUE (code),
    CONSTRAINT feed_sources_ttl_minutes_check CHECK (ttl_minutes > 0)
  );

  CREATE TABLE import_jobs (
    id bigserial PRIMARY KEY NOT NULL,
    feed_source_id integer NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    status import_job_status DEFAULT 'Pending' NOT NULL,
    started_at timestamptz DEFAULT now() NOT NULL,
    finished_at timestamptz,
    records_seen integer DEFAULT 0 NOT NULL,
    records_inserted integer DEFAULT 0 NOT NULL,
    records_updated integer DEFAULT 0 NOT NULL,
    records_expired integer DEFAULT 0 NOT NULL,
    records_failed integer DEFAULT 0 NOT NULL,
    file_reference text,
    checksum text,
    created_at timestamptz DEFAULT now() NOT NULL
  );

  CREATE TABLE import_errors (
    id bigserial PRIMARY KEY NOT NULL,
    import_job_id bigint NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    feed_source_id integer NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_listing_id text,
    error_type text NOT NULL,
    error_message text NOT NULL,
    raw_payload jsonb,
    occurred_at timestamptz DEFAULT now() NOT NULL
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
