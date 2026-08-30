"""``import_run`` — open an ``import_jobs`` row, track per-record outcomes, close it.

Tracking runs on its own autocommit connection, separate from whatever connection
a feed importer uses for listing data. The job row is committed the moment the run
opens, every error row is committed as it is recorded, and the close commits
regardless of what happened to the importer's data transaction — so a rolled-back
or crashed run still leaves a closed ``import_jobs`` row, never one stuck at
``Running``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from iol_importers.config import resolve_database_url

ErrorType = Literal["validation", "parse", "db_insert", "mapping"]
_ERROR_TYPES: frozenset[str] = frozenset(("validation", "parse", "db_insert", "mapping"))

_REQUIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("feed_sources", "ttl_days"),
    ("import_jobs", "records_skipped"),
    ("import_jobs", "error_message"),
)


class SchemaNotReadyError(RuntimeError):
    """The feed-infrastructure columns from db/migrations/002_* are not present."""


class FeedSourceNotFoundError(RuntimeError):
    """No feed_sources row has the given code. Feed sources are configuration."""


@dataclass(frozen=True, slots=True)
class RunCounts:
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    expired: int = 0
    failed: int = 0


class ImportRun:
    """Handle passed to importer code for the duration of one run."""

    def __init__(self, conn: psycopg.Connection, job_id: int, feed_source_id: int) -> None:
        self._conn = conn
        self.job_id = job_id
        self.feed_source_id = feed_source_id
        self._seen = 0
        self._inserted = 0
        self._updated = 0
        self._skipped = 0
        self._expired = 0
        self._failed = 0

    def seen(self, n: int = 1) -> None:
        self._seen += n

    def inserted(self, n: int = 1) -> None:
        self._inserted += n

    def updated(self, n: int = 1) -> None:
        self._updated += n

    def skipped(self, n: int = 1) -> None:
        self._skipped += n

    def expired(self, n: int = 1) -> None:
        self._expired += n

    def record_error(
        self,
        *,
        vendor_listing_id: str | None,
        error_type: ErrorType,
        error_message: str,
        raw_payload: object,
    ) -> None:
        """Write one import_errors row and count the failure. Does not raise on a
        bad record — the rest of the run continues.

        ``raw_payload`` is stored exactly as received: a dict/list becomes a JSON
        object/array, a str or bytes becomes a JSON string scalar. Nothing here
        parses or normalises it.
        """
        if error_type not in _ERROR_TYPES:
            raise ValueError(
                f"error_type must be one of {sorted(_ERROR_TYPES)}, got {error_type!r}"
            )
        self._conn.execute(
            """
            INSERT INTO import_errors
                (import_job_id, feed_source_id, vendor_listing_id,
                 error_type, error_message, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                self.job_id,
                self.feed_source_id,
                vendor_listing_id,
                error_type,
                error_message,
                _as_jsonb(raw_payload),
            ),
        )
        self._failed += 1

    @property
    def counts(self) -> RunCounts:
        return RunCounts(
            seen=self._seen,
            inserted=self._inserted,
            updated=self._updated,
            skipped=self._skipped,
            expired=self._expired,
            failed=self._failed,
        )


def _as_jsonb(payload: object) -> Jsonb:
    # bytes cannot be JSON-encoded directly; decode to the string it represents.
    # This is an encoding step, not normalisation — the value is still verbatim.
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    return Jsonb(payload)


def _format_exception(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _assert_schema_ready(cur: psycopg.Cursor) -> None:
    for table, column in _REQUIRED_COLUMNS:
        cur.execute(
            """
            SELECT 1
            FROM pg_attribute
            WHERE attrelid = %s::regclass
              AND attname = %s
              AND attnum > 0
              AND NOT attisdropped
            """,
            (table, column),
        )
        if cur.fetchone() is None:
            raise SchemaNotReadyError(
                f"{table}.{column} is missing — apply "
                "db/migrations/002_feed_infrastructure.sql in DataGrip and run "
                "`pnpm db:pull`, then retry."
            )


def _resolve_feed_source(cur: psycopg.Cursor, code: str) -> int:
    cur.execute("SELECT id FROM feed_sources WHERE code = %s", (code,))
    row = cur.fetchone()
    if row is None:
        raise FeedSourceNotFoundError(
            f"no feed_sources row with code {code!r} — feed sources are seeded "
            "configuration and are never created by an import run."
        )
    return row["id"]


def _default_connect() -> psycopg.Connection:
    # Autocommit: tracking rows must persist independently of the importer's own
    # data transaction, so each statement here commits on its own.
    return psycopg.connect(resolve_database_url(), autocommit=True, row_factory=dict_row)


def _close(
    conn: psycopg.Connection,
    run: ImportRun,
    *,
    status: str,
    error_message: str | None,
) -> None:
    counts = run.counts
    conn.execute(
        """
        UPDATE import_jobs SET
            status = %s,
            finished_at = now(),
            records_seen = %s,
            records_inserted = %s,
            records_updated = %s,
            records_skipped = %s,
            records_expired = %s,
            records_failed = %s,
            error_message = %s
        WHERE id = %s
        """,
        (
            status,
            counts.seen,
            counts.inserted,
            counts.updated,
            counts.skipped,
            counts.expired,
            counts.failed,
            error_message,
            run.job_id,
        ),
    )


@contextmanager
def import_run(
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
    file_reference: str | None = None,
    checksum: str | None = None,
) -> Iterator[ImportRun]:
    """Open an ``import_jobs`` row, yield an :class:`ImportRun`, then close the row.

    Clean exit with no failed records → ``Success``; clean exit with at least one
    failed record → ``PartialSuccess``; any exception (including ``KeyboardInterrupt``)
    → ``Failed`` with ``error_message`` set, and the exception is re-raised.
    """
    conn = (connect or _default_connect)()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            _assert_schema_ready(cur)
            feed_source_id = _resolve_feed_source(cur, feed_source_code)
            cur.execute(
                """
                INSERT INTO import_jobs
                    (feed_source_id, status, started_at, file_reference, checksum)
                VALUES (%s, 'Running', now(), %s, %s)
                RETURNING id
                """,
                (feed_source_id, file_reference, checksum),
            )
            job_id = cur.fetchone()["id"]

        run = ImportRun(conn=conn, job_id=job_id, feed_source_id=feed_source_id)
        try:
            yield run
        except BaseException as exc:
            _close_best_effort(conn, run, status="Failed", error_message=_format_exception(exc))
            raise
        else:
            status = "Success" if run.counts.failed == 0 else "PartialSuccess"
            _close(conn, run, status=status, error_message=None)
    finally:
        conn.close()


def _close_best_effort(
    conn: psycopg.Connection, run: ImportRun, *, status: str, error_message: str | None
) -> None:
    # The exception being handled must win; closing the row is best effort.
    with suppress(Exception):
        _close(conn, run, status=status, error_message=error_message)
