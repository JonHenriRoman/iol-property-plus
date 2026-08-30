"""A throwaway schema holding the Domain 6 tables, for exercising ``import_run``
offline — used by ``feeds.demo`` and by the database tests.

The three real tables live in the DataGrip-owned database; this rebuilds their
relevant shape (post-migration-002) in an isolated schema so committed tracking
rows can be inspected and then dropped without touching ``iol_property_plus``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

SCRATCH_DDL = """
CREATE TYPE import_job_status AS ENUM
    ('Pending', 'Running', 'Success', 'PartialSuccess', 'Failed');

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
"""


def _resolve_url(url: str | None) -> str:
    resolved = url or os.environ.get("TEST_DATABASE_URL")
    if not resolved:
        raise RuntimeError("pass a URL or set TEST_DATABASE_URL to run the scratch schema")
    return resolved


@contextmanager
def scratch_schema(url: str | None = None) -> Iterator[Callable[[], psycopg.Connection]]:
    """Create an isolated schema with the Domain 6 tables; drop it on exit.

    Yields a connection factory whose ``search_path`` is pinned to that schema —
    hand it straight to ``import_run(connect=...)``.
    """
    resolved = _resolve_url(url)
    name = f"feeds_scratch_{os.getpid()}"

    admin = psycopg.connect(resolved, autocommit=True)
    try:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        admin.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(name))
        )
        admin.execute(SCRATCH_DDL)

        def connect() -> psycopg.Connection:
            return psycopg.connect(
                resolved,
                autocommit=True,
                row_factory=dict_row,
                options=f"-c search_path={name}",
            )

        try:
            yield connect
        finally:
            admin.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
            )
    finally:
        admin.close()
