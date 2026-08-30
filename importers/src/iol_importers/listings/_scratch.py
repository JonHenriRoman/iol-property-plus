"""A throwaway schema with the Domain 4 neighbourhood (post-migration 001+002+003),
for exercising the listing importer offline — used by ``listings.demo`` and the
database tests.

Mirrors the relevant shape of the DataGrip-owned tables plus the two listings
triggers in their migration-003 form, in an isolated schema that is dropped
``CASCADE`` afterwards so committed rows never touch ``iol_property_plus``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SCRATCH_DDL = """
CREATE TYPE listing_type AS ENUM ('Sale', 'Rental', 'Unknown');
CREATE TYPE listing_status AS ENUM
    ('Active', 'UnderOffer', 'Sold', 'Rented', 'Expired', 'Withdrawn', 'Draft');
CREATE TYPE price_change_type AS ENUM ('Initial', 'Increase', 'Decrease', 'Relisted');
CREATE TYPE import_job_status AS ENUM
    ('Pending', 'Running', 'Success', 'PartialSuccess', 'Failed');

CREATE FUNCTION trg_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN NEW.updated_at := now(); RETURN NEW; END $fn$;

CREATE TABLE feed_sources (
    id serial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    vendor_name text NOT NULL DEFAULT 'demo',
    ttl_days smallint NOT NULL DEFAULT 14,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feed_sources_ttl_days_check CHECK (ttl_days > 0)
);

CREATE TABLE import_jobs (
    id bigserial PRIMARY KEY,
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    status import_job_status NOT NULL DEFAULT 'Pending',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    records_seen int NOT NULL DEFAULT 0,
    records_inserted int NOT NULL DEFAULT 0,
    records_updated int NOT NULL DEFAULT 0,
    records_skipped int NOT NULL DEFAULT 0,
    records_expired int NOT NULL DEFAULT 0,
    records_failed int NOT NULL DEFAULT 0,
    error_message text,
    file_reference text,
    checksum text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE import_errors (
    id bigserial PRIMARY KEY,
    import_job_id bigint NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_listing_id text,
    error_type text NOT NULL,
    error_message text NOT NULL,
    raw_payload jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT import_errors_error_type_check
        CHECK (error_type IN ('validation', 'parse', 'db_insert', 'mapping'))
);

CREATE TABLE provinces (
    id serial PRIMARY KEY,
    name text NOT NULL,
    code text NOT NULL,
    country_code char(2) NOT NULL DEFAULT 'ZA'
);
CREATE TABLE cities (
    id serial PRIMARY KEY,
    province_id int NOT NULL REFERENCES provinces(id),
    name text NOT NULL,
    slug text NOT NULL
);
CREATE TABLE suburbs (
    id serial PRIMARY KEY,
    city_id int NOT NULL REFERENCES cities(id),
    name text NOT NULL,
    slug text NOT NULL,
    postal_code text,
    extension varchar(100),
    external_id integer,
    alternate_names text,
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE property_types (
    id serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    slug text NOT NULL UNIQUE,
    category text NOT NULL DEFAULT 'Residential'
);

CREATE TABLE property_type_vendor_mappings (
    id bigserial PRIMARY KEY,
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_value text NOT NULL,
    property_type_id int NOT NULL REFERENCES property_types(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_property_type_vendor_mappings UNIQUE (feed_source_id, vendor_value)
);

CREATE TABLE agencies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    email text,
    phone text,
    status text NOT NULL DEFAULT 'Active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE agents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id uuid REFERENCES agencies(id) ON DELETE SET NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    display_name text,
    email text,
    status text NOT NULL DEFAULT 'Active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE agency_vendor_ids (
    id bigserial PRIMARY KEY,
    agency_id uuid NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_agency_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_agency_vendor_ids UNIQUE (feed_source_id, vendor_agency_id)
);
CREATE TABLE agent_vendor_ids (
    id bigserial PRIMARY KEY,
    agent_id uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_agent_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_vendor_ids UNIQUE (feed_source_id, vendor_agent_id)
);

CREATE TABLE listings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    feed_source_id int NOT NULL REFERENCES feed_sources(id) ON DELETE RESTRICT,
    vendor_listing_id text NOT NULL,
    agency_id uuid REFERENCES agencies(id) ON DELETE SET NULL,
    agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
    property_type_id int NOT NULL REFERENCES property_types(id) ON DELETE RESTRICT,
    suburb_id int REFERENCES suburbs(id) ON DELETE RESTRICT,
    listing_type listing_type NOT NULL DEFAULT 'Unknown',
    status listing_status NOT NULL DEFAULT 'Active',
    price numeric(14,2),
    price_on_application boolean NOT NULL DEFAULT false,
    currency char(3) NOT NULL DEFAULT 'ZAR',
    bedrooms smallint CHECK (bedrooms IS NULL OR bedrooms >= 0),
    bathrooms numeric(3,1) CHECK (bathrooms IS NULL OR bathrooms >= 0),
    garages smallint CHECK (garages IS NULL OR garages >= 0),
    parking_spaces smallint CHECK (parking_spaces IS NULL OR parking_spaces >= 0),
    erf_size_sqm numeric(10,2) CHECK (erf_size_sqm IS NULL OR erf_size_sqm >= 0),
    floor_size_sqm numeric(10,2) CHECK (floor_size_sqm IS NULL OR floor_size_sqm >= 0),
    levies numeric(10,2),
    rates_and_taxes numeric(10,2),
    title text NOT NULL,
    description text,
    street_address text,
    complex_name text,
    unit_number text,
    latitude numeric(9,6),
    longitude numeric(9,6),
    features text[] NOT NULL DEFAULT '{}',
    primary_image_url text,
    is_featured boolean NOT NULL DEFAULT false,
    listed_at timestamptz,
    last_updated_by_vendor_at timestamptz,
    first_imported_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now(),
    expired_at timestamptz,
    raw_data jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_listings_feed_vendor UNIQUE (feed_source_id, vendor_listing_id),
    CONSTRAINT listings_price_check CHECK (price IS NULL OR price >= 0)
);

CREATE TABLE listing_price_history (
    id bigserial PRIMARY KEY,
    listing_id uuid NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    old_price numeric(14,2),
    new_price numeric(14,2),
    change_type price_change_type NOT NULL,
    import_job_id bigint REFERENCES import_jobs(id) ON DELETE SET NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION trg_listings_set_expiry() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE v_ttl_days SMALLINT;
BEGIN
    IF TG_OP = 'INSERT' OR NEW.last_seen_at IS DISTINCT FROM OLD.last_seen_at THEN
        SELECT ttl_days INTO v_ttl_days FROM feed_sources WHERE id = NEW.feed_source_id;
        NEW.expires_at := NEW.last_seen_at + make_interval(days => coalesce(v_ttl_days, 14));
        IF NEW.status = 'Expired' THEN
            NEW.status := 'Active';
            NEW.expired_at := NULL;
        END IF;
    END IF;
    RETURN NEW;
END $fn$;

CREATE FUNCTION trg_listings_log_price_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
DECLARE v_job_id BIGINT := nullif(current_setting('app.current_import_job', true), '')::bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO listing_price_history
            (listing_id, old_price, new_price, change_type, import_job_id)
        VALUES (NEW.id, NULL, NEW.price, 'Initial', v_job_id);
    ELSIF TG_OP = 'UPDATE' AND NEW.price IS DISTINCT FROM OLD.price THEN
        INSERT INTO listing_price_history
            (listing_id, old_price, new_price, change_type, import_job_id)
        VALUES (NEW.id, OLD.price, NEW.price,
                CASE WHEN OLD.price IS NULL OR NEW.price IS NULL THEN 'Relisted'
                     WHEN NEW.price > OLD.price THEN 'Increase'
                     ELSE 'Decrease' END::price_change_type,
                v_job_id);
    END IF;
    RETURN NEW;
END $fn$;

CREATE TRIGGER trg_listings_expiry BEFORE INSERT OR UPDATE ON listings
    FOR EACH ROW EXECUTE FUNCTION trg_listings_set_expiry();
CREATE TRIGGER trg_listings_price_history AFTER INSERT OR UPDATE ON listings
    FOR EACH ROW EXECUTE FUNCTION trg_listings_log_price_change();
CREATE TRIGGER trg_listings_updated_at BEFORE UPDATE ON listings
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();
"""

# Reference data every listing import needs. Kept small and deterministic.
SEED_SQL = """
INSERT INTO feed_sources (code, name, ttl_days) VALUES ('demo-feed', 'Demo Feed', 7);
INSERT INTO provinces (name, code) VALUES ('Western Cape', 'WC'), ('Gauteng', 'GP');
INSERT INTO cities (province_id, name, slug) VALUES
    ((SELECT id FROM provinces WHERE code = 'WC'), 'Cape Town', 'cape-town'),
    ((SELECT id FROM provinces WHERE code = 'GP'), 'Johannesburg', 'johannesburg');
INSERT INTO suburbs (city_id, name, slug, alternate_names)
SELECT c.id, v.name, v.slug, v.alt
FROM (VALUES
    ('cape-town',    'Claremont',  'claremont',  NULL),
    ('cape-town',    'Rondebosch', 'rondebosch', NULL),
    ('johannesburg', 'Sandton',    'sandton',    'Sandton CBD | Sandhurst'),
    ('johannesburg', 'Rosebank',   'rosebank',   NULL)
) AS v(city_slug, name, slug, alt)
JOIN cities c ON c.slug = v.city_slug;
INSERT INTO property_types (name, slug) VALUES
    ('House', 'house'), ('Apartment', 'apartment'), ('Townhouse', 'townhouse'),
    ('Vacant Land', 'vacant-land'), ('Cluster', 'cluster'), ('Farm', 'farm'),
    ('Apartment Block', 'apartment-block'), ('Office', 'office'),
    ('Workshop', 'workshop'), ('Residential Estate', 'residential-estate'),
    ('Development', 'development');
"""


def _resolve_url(url: str | None) -> str:
    resolved = url or os.environ.get("TEST_DATABASE_URL")
    if not resolved:
        raise RuntimeError("pass a URL or set TEST_DATABASE_URL to run the scratch schema")
    return resolved


@dataclass(frozen=True, slots=True)
class ScratchDB:
    """Connection factories pinned to the scratch schema."""

    url: str
    schema: str

    def connect(self, *, autocommit: bool = False) -> psycopg.Connection:
        return psycopg.connect(
            self.url,
            autocommit=autocommit,
            row_factory=dict_row,
            options=f"-c search_path={self.schema}",
        )

    def data_connect(self) -> psycopg.Connection:
        return self.connect()

    def tracking_connect(self) -> psycopg.Connection:
        return self.connect(autocommit=True)


@contextmanager
def scratch_schema(url: str | None = None, *, seed: bool = True) -> Iterator[ScratchDB]:
    """Create an isolated schema with the Domain 4 tables (and optional seed data);
    drop it on exit."""
    resolved = _resolve_url(url)
    name = f"listings_scratch_{os.getpid()}"

    admin = psycopg.connect(resolved, autocommit=True)
    try:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        admin.execute(SCRATCH_DDL)
        if seed:
            admin.execute(SEED_SQL)
        try:
            yield ScratchDB(url=resolved, schema=name)
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
            )
    finally:
        admin.close()
