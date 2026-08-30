-- 001_suburbs_property24_columns.sql
--
-- Prerequisite for the Property24 suburb seed importer (importers/, `pnpm run seed:suburbs`).
--
-- DataGrip owns DDL for iol_property_plus; this repo only introspects. Apply this
-- migration by hand in DataGrip, then run `pnpm db:pull` to regenerate
-- src/server/db/{schema,relations}.ts. The importer refuses to start until these
-- columns and constraints exist.
--
-- Why each change:
--
--   extension        Property24's canonical suburb feed carries an Extension column
--                    ("Ext 1", "Lotusville") that distinguishes estates/sections
--                    within one suburb name. 14,135 of 20,755 South African rows
--                    populate it. Without a real column the feed collapses from
--                    20,755 rows to 6,620 (a 68% loss).
--
--   external_id      Property24's stable numeric suburb Id. The importer upserts
--                    on this so re-running against a refreshed download updates
--                    existing rows instead of duplicating them.
--
--   alternate_names  Property24's free-text alternate-spelling value, stored as-is
--                    (single value in this feed, not delimiter-separated).
--
-- Server is PostgreSQL 16.15, so UNIQUE ... NULLS NOT DISTINCT is available.

BEGIN;

ALTER TABLE suburbs
  ADD COLUMN extension       VARCHAR(100),
  ADD COLUMN external_id     INTEGER,
  ADD COLUMN alternate_names TEXT;

-- (city_id, name) is no longer unique once extensions exist: many rows share a
-- suburb name within one city and differ only by extension. NULLS NOT DISTINCT
-- keeps two extension-less rows from sharing a name in the same city.
ALTER TABLE suburbs DROP CONSTRAINT uq_suburbs_city_name;

ALTER TABLE suburbs
  ADD CONSTRAINT uq_suburbs_city_name_extension
  UNIQUE NULLS NOT DISTINCT (city_id, name, extension);

-- The importer's upsert key.
ALTER TABLE suburbs
  ADD CONSTRAINT uq_suburbs_external_id UNIQUE (external_id);

COMMIT;
