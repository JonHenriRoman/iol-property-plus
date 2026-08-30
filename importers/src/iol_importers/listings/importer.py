"""``import_listings`` — normalise, resolve, upsert a batch of vendor listing records.

Uses the Domain 6 ``import_run`` scaffolding for job/error tracking (its own
autocommit connection) and a separate data connection for the ``listings`` work.
Each record is handled in its own transaction: a failure is caught, written to
``import_errors`` with the right ``error_type``, counted, and the batch continues.

Price history and ``expires_at`` are left to the database triggers
(``trg_listings_log_price_change`` / ``trg_listings_set_expiry``); the importer
just sets ``price`` and ``last_seen_at`` and exposes the job id to the price
trigger via the ``app.current_import_job`` session setting.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts, import_run

from .normalize import (
    RecordParseError,
    clean_str,
    normalize_listing_type,
    to_bool,
    to_decimal,
    to_int,
    to_str_list,
)
from .resolve import (
    MappingError,
    resolve_agency,
    resolve_agent,
    resolve_property_type,
    resolve_suburb,
)


class ListingValidationError(ValueError):
    """A required field is missing/blank — routes to error_type='validation'."""


class SchemaNotReadyError(RuntimeError):
    """listings-domain migrations (001 + 002 + 003) are not fully applied."""


# Vendor record keys the importer lifts into typed columns. Everything else in a
# record is kept verbatim in listings.raw_data. Promote a column later by adding
# its source key here and a line to _process_record.
PROMOTED_KEYS: frozenset[str] = frozenset(
    {
        "vendor_listing_id",
        "vendor_listing_type",
        "listing_type",
        "property_type",
        "suburb",
        "suburb_extension",
        "agency_vendor_id",
        "agency_name",
        "agent_vendor_id",
        "agent_name",
        "price",
        "price_on_application",
        "bedrooms",
        "bathrooms",
        "garages",
        "parking_spaces",
        "erf_size",
        "floor_size",
        "levies",
        "rates_and_taxes",
        "title",
        "description",
        "street_address",
        "complex_name",
        "unit_number",
        "latitude",
        "longitude",
        "features",
        "primary_image_url",
        "listed_at",
        "vendor_updated_at",
    }
)

# listings columns written on every upsert, in order. feed_source_id and
# vendor_listing_id are the conflict key and never in the UPDATE SET clause;
# last_seen_at is always now(); the rest come from the record.
_KEY_COLUMNS = ("feed_source_id", "vendor_listing_id")
_VALUE_COLUMNS = (
    "agency_id",
    "agent_id",
    "property_type_id",
    "suburb_id",
    "listing_type",
    "price",
    "price_on_application",
    "bedrooms",
    "bathrooms",
    "garages",
    "parking_spaces",
    "erf_size_sqm",
    "floor_size_sqm",
    "levies",
    "rates_and_taxes",
    "title",
    "description",
    "street_address",
    "complex_name",
    "unit_number",
    "latitude",
    "longitude",
    "features",
    "primary_image_url",
    "listed_at",
    "last_updated_by_vendor_at",
    "raw_data",
)


def _build_upsert_sql() -> str:
    cols = (*_KEY_COLUMNS, *_VALUE_COLUMNS, "last_seen_at")
    placeholders = [f"%({c})s" for c in (*_KEY_COLUMNS, *_VALUE_COLUMNS)] + ["now()"]
    set_clause = ",\n            ".join(f"{c} = EXCLUDED.{c}" for c in _VALUE_COLUMNS)
    return f"""
        INSERT INTO listings ({", ".join(cols)})
        VALUES ({", ".join(placeholders)})
        ON CONFLICT (feed_source_id, vendor_listing_id) DO UPDATE SET
            {set_clause},
            last_seen_at = now()
        RETURNING (xmax = 0) AS inserted
    """


_UPSERT_SQL = _build_upsert_sql()


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _assert_schema_ready(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT to_regclass('property_type_vendor_mappings') AS t")
    if cur.fetchone()["t"] is None:
        raise SchemaNotReadyError(
            "property_type_vendor_mappings is missing — apply "
            "db/migrations/003_listings_importer.sql in DataGrip and run `pnpm db:pull`."
        )
    cur.execute(
        """
        SELECT attnotnull
        FROM pg_attribute
        WHERE attrelid = 'listings'::regclass AND attname = 'suburb_id'
        """
    )
    if cur.fetchone()["attnotnull"]:
        raise SchemaNotReadyError(
            "listings.suburb_id is still NOT NULL — apply "
            "db/migrations/003_listings_importer.sql in DataGrip."
        )
    cur.execute(
        """
        SELECT 1 FROM pg_attribute
        WHERE attrelid = 'suburbs'::regclass AND attname = 'alternate_names' AND NOT attisdropped
        """
    )
    if cur.fetchone() is None:
        raise SchemaNotReadyError(
            "suburbs.alternate_names is missing — apply "
            "db/migrations/001_suburbs_property24_columns.sql in DataGrip."
        )


def _row_from_record(
    cur: psycopg.Cursor, feed_source_id: int, record: Mapping[str, Any]
) -> dict[str, Any]:
    vendor_listing_id = clean_str(record.get("vendor_listing_id"))
    if vendor_listing_id is None:
        raise ListingValidationError("vendor_listing_id is required")

    title = clean_str(record.get("title"))
    if title is None:
        raise ListingValidationError("title is required")

    property_type_id = resolve_property_type(
        cur, feed_source_id, record.get("property_type"), record.get("vendor_listing_type")
    )
    suburb_id = resolve_suburb(cur, record.get("suburb"), record.get("suburb_extension"))
    agency_id = resolve_agency(
        cur, feed_source_id, record.get("agency_vendor_id"), record.get("agency_name")
    )
    agent_id = resolve_agent(
        cur,
        feed_source_id,
        record.get("agent_vendor_id"),
        record.get("agent_name"),
        agency_id,
    )

    raw_data = {k: v for k, v in record.items() if k not in PROMOTED_KEYS}

    return {
        "feed_source_id": feed_source_id,
        "vendor_listing_id": vendor_listing_id,
        "agency_id": agency_id,
        "agent_id": agent_id,
        "property_type_id": property_type_id,
        "suburb_id": suburb_id,
        "listing_type": normalize_listing_type(record.get("listing_type")),
        "price": to_decimal(record.get("price"), field="price"),
        "price_on_application": to_bool(
            record.get("price_on_application"), field="price_on_application"
        )
        or False,
        "bedrooms": to_int(record.get("bedrooms"), field="bedrooms"),
        "bathrooms": to_decimal(record.get("bathrooms"), field="bathrooms"),
        "garages": to_int(record.get("garages"), field="garages"),
        "parking_spaces": to_int(record.get("parking_spaces"), field="parking_spaces"),
        "erf_size_sqm": to_decimal(record.get("erf_size"), field="erf_size"),
        "floor_size_sqm": to_decimal(record.get("floor_size"), field="floor_size"),
        "levies": to_decimal(record.get("levies"), field="levies"),
        "rates_and_taxes": to_decimal(record.get("rates_and_taxes"), field="rates_and_taxes"),
        "title": title,
        "description": clean_str(record.get("description")),
        "street_address": clean_str(record.get("street_address")),
        "complex_name": clean_str(record.get("complex_name")),
        "unit_number": clean_str(record.get("unit_number")),
        "latitude": to_decimal(record.get("latitude"), field="latitude"),
        "longitude": to_decimal(record.get("longitude"), field="longitude"),
        "features": to_str_list(record.get("features")),
        "primary_image_url": clean_str(record.get("primary_image_url")),
        "listed_at": clean_str(record.get("listed_at")),
        "last_updated_by_vendor_at": clean_str(record.get("vendor_updated_at")),
        "raw_data": Jsonb(raw_data),
    }


_ERROR_TYPE_BY_EXC: tuple[tuple[type[Exception], str], ...] = (
    (ListingValidationError, "validation"),
    (RecordParseError, "parse"),
    (MappingError, "mapping"),
)


def import_listings(
    records: Iterable[Mapping[str, Any]],
    *,
    feed_source_code: str,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    file_reference: str | None = None,
) -> RunCounts:
    """Import a batch of already-parsed vendor listing records. Returns the counts."""
    data_conn = (connect or _default_connect)()
    try:
        # Guard the schema before a job row is opened, so an unmigrated database
        # fails cleanly with no stray import_jobs row.
        with data_conn.cursor(row_factory=dict_row) as setup:
            _assert_schema_ready(setup)
        data_conn.rollback()

        with import_run(
            feed_source_code, connect=tracking_connect, file_reference=file_reference
        ) as run:
            with data_conn.cursor(row_factory=dict_row) as setup:
                setup.execute(
                    "SELECT set_config('app.current_import_job', %s, false)", (str(run.job_id),)
                )
            data_conn.commit()

            for record in records:
                run.seen()
                vendor_listing_id = clean_str(record.get("vendor_listing_id"))
                try:
                    with data_conn.transaction():
                        cur = data_conn.cursor(row_factory=dict_row)
                        params = _row_from_record(cur, run.feed_source_id, record)
                        cur.execute(_UPSERT_SQL, params)
                        inserted = cur.fetchone()["inserted"]
                    if inserted:
                        run.inserted()
                    else:
                        run.updated()
                except (ListingValidationError, RecordParseError, MappingError) as exc:
                    run.record_error(
                        vendor_listing_id=vendor_listing_id,
                        error_type=_error_type_for(exc),
                        error_message=str(exc),
                        raw_payload=dict(record),
                    )
                except psycopg.Error as exc:
                    run.record_error(
                        vendor_listing_id=vendor_listing_id,
                        error_type="db_insert",
                        error_message=str(exc).strip(),
                        raw_payload=dict(record),
                    )
            return run.counts
    finally:
        data_conn.close()


def _error_type_for(exc: Exception) -> str:
    for exc_type, name in _ERROR_TYPE_BY_EXC:
        if isinstance(exc, exc_type):
            return name
    return "validation"
