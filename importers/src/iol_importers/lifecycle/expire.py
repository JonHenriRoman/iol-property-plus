"""The scheduled listing-expiry sweep.

    UPDATE listings SET status = 'Expired', expired_at = now()
    WHERE status = 'Active' AND expires_at < now();

One atomic statement:

* touches only ``status`` and ``expired_at`` (``updated_at`` is bumped by the
  existing ``trg_listings_updated_at`` trigger); never deletes a row, never
  writes ``expires_at``;
* idempotent — the ``status = 'Active'`` filter means a second run matches
  nothing and changes zero rows;
* reads live ``expires_at`` — the predicate is evaluated per row at execution
  time, so a listing whose ``expires_at`` was just refreshed by an importer run
  is never expired here.

Intended to run nightly, after the feed imports — see ``cli.py`` and the READMEs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url

_EXPIRE_SQL = """
    UPDATE listings
    SET status = 'Expired', expired_at = now()
    WHERE status = 'Active' AND expires_at < now()
"""

_PENDING_SQL = """
    SELECT count(*) AS n
    FROM listings
    WHERE status = 'Active' AND expires_at < now()
"""


@dataclass(frozen=True, slots=True)
class ExpiryResult:
    expired_count: int
    status_before: dict[str, int]
    status_after: dict[str, int]


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _status_counts(cur: psycopg.Cursor) -> dict[str, int]:
    cur.execute("SELECT status::text AS status, count(*) AS n FROM listings GROUP BY status")
    return {row["status"]: row["n"] for row in cur.fetchall()}


def expire_listings(
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
    dry_run: bool = False,
) -> ExpiryResult:
    """Run the sweep once. With ``dry_run`` the UPDATE is not issued and
    ``expired_count`` is the number of rows that *would* be expired."""
    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            before = _status_counts(cur)
            if dry_run:
                cur.execute(_PENDING_SQL)
                expired = cur.fetchone()["n"]
                after = before
            else:
                cur.execute(_EXPIRE_SQL)
                expired = cur.rowcount
                after = _status_counts(cur)
        return ExpiryResult(expired_count=expired, status_before=before, status_after=after)
    finally:
        conn.close()
