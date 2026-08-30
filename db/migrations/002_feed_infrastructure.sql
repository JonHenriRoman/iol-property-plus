-- 002_feed_infrastructure.sql
--
-- Prerequisite for the shared feed import-run / error-tracking module
-- (importers/src/iol_importers/feeds/). canonical-database-design.md Domain 6.
--
-- DataGrip owns DDL for iol_property_plus; this repo only introspects. Apply this
-- migration by hand in DataGrip, then run `pnpm db:pull` to regenerate
-- src/server/db/{schema,relations}.ts. The tracking module refuses to start until
-- these columns and constraints exist.
--
-- feed_sources, import_jobs and import_errors are all empty, so nothing converts.
--
-- Why each change:
--
--   ttl_days            The expiry lifecycle the doc specifies is in days, default
--                       14. The live column ttl_minutes (default 1440 = 1 day) is
--                       the same concept in a different unit and is read by no
--                       application code — replaced outright rather than left to
--                       drift against a second column.
--
--   records_skipped     import_jobs already has records_expired ("listing dropped
--                       out of the feed"). "Skipped" is a distinct outcome — a
--                       record we chose not to process — and needs its own counter.
--
--   error_message       import_jobs had nowhere to record why a run failed.
--
--   error_type CHECK    import_errors.error_type was free text; the doc fixes it to
--                       four values.

BEGIN;

ALTER TABLE feed_sources DROP CONSTRAINT feed_sources_ttl_minutes_check;
ALTER TABLE feed_sources DROP COLUMN ttl_minutes;
ALTER TABLE feed_sources ADD COLUMN ttl_days SMALLINT NOT NULL DEFAULT 14;
ALTER TABLE feed_sources ADD CONSTRAINT feed_sources_ttl_days_check CHECK (ttl_days > 0);

ALTER TABLE import_jobs ADD COLUMN records_skipped INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_jobs ADD COLUMN error_message TEXT;

ALTER TABLE import_errors ADD CONSTRAINT import_errors_error_type_check
  CHECK (error_type IN ('validation', 'parse', 'db_insert', 'mapping'));

COMMIT;
