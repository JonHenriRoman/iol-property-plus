-- 003_listings_importer.sql
--
-- Prerequisite for the core listing importer
-- (importers/src/iol_importers/listings/). canonical-database-design.md Domain 4.
--
-- DataGrip owns DDL for iol_property_plus; this repo only introspects. Apply this
-- migration by hand in DataGrip **after 002** (002 drops feed_sources.ttl_minutes,
-- which the existing trg_listings_set_expiry still reads — this migration is what
-- makes that trigger work again). Then run `pnpm db:pull`.
--
-- The importer refuses to start until these changes are present.
--
-- Why each change:
--
--   listings.suburb_id nullable    Suburb resolution legitimately fails for a
--                                  meaningful share of feed records (the doc says
--                                  ~16%). A listing with an unresolved suburb
--                                  still imports rather than being rejected.
--
--   property_type_vendor_mappings  Per-feed mapping of a vendor's property-type
--                                  string to a canonical property_types row, so
--                                  resolution is a table lookup, not a magic
--                                  string buried in code.
--
--   trg_listings_set_expiry        Rewritten to read feed_sources.ttl_days
--                                  (was ttl_minutes, removed by 002).
--
--   trg_listings_log_price_change  Now stamps import_job_id onto the price-history
--                                  row it writes, read from the per-run session
--                                  setting app.current_import_job.

BEGIN;

ALTER TABLE listings ALTER COLUMN suburb_id DROP NOT NULL;

CREATE TABLE property_type_vendor_mappings (
    id               bigserial   PRIMARY KEY,
    feed_source_id   integer     NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,
    vendor_value     text        NOT NULL,
    property_type_id integer     NOT NULL REFERENCES property_types(id) ON DELETE RESTRICT,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_property_type_vendor_mappings UNIQUE (feed_source_id, vendor_value)
);

CREATE INDEX idx_property_type_vendor_mappings_property_type_id
    ON property_type_vendor_mappings (property_type_id);

CREATE OR REPLACE FUNCTION trg_listings_set_expiry() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_ttl_days SMALLINT;
BEGIN
    IF TG_OP = 'INSERT' OR NEW.last_seen_at IS DISTINCT FROM OLD.last_seen_at THEN
        SELECT ttl_days INTO v_ttl_days
        FROM feed_sources
        WHERE id = NEW.feed_source_id;

        NEW.expires_at := NEW.last_seen_at + make_interval(days => coalesce(v_ttl_days, 14));

        -- A listing that's been freshly seen again is, by definition, back —
        -- clear a prior Expired state so the next import naturally revives it.
        IF NEW.status = 'Expired' THEN
            NEW.status := 'Active';
            NEW.expired_at := NULL;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION trg_listings_log_price_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    v_job_id BIGINT := nullif(current_setting('app.current_import_job', true), '')::bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO listing_price_history
            (listing_id, old_price, new_price, change_type, import_job_id)
        VALUES (NEW.id, NULL, NEW.price, 'Initial', v_job_id);
    ELSIF TG_OP = 'UPDATE' AND NEW.price IS DISTINCT FROM OLD.price THEN
        INSERT INTO listing_price_history
            (listing_id, old_price, new_price, change_type, import_job_id)
        VALUES (
            NEW.id, OLD.price, NEW.price,
            CASE
                WHEN OLD.price IS NULL OR NEW.price IS NULL THEN 'Relisted'
                WHEN NEW.price > OLD.price THEN 'Increase'
                ELSE 'Decrease'
            END::price_change_type,
            v_job_id
        );
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
