"""Soft-delete listings a feed has explicitly removed.

Most feeds never send a delete — a withdrawn listing just stops appearing, and
``expire_listings`` catches it once ``expires_at`` passes. RE/MAX (and some
others) *do* send an explicit deletion list. This marks the matching rows
``Withdrawn`` — it never deletes a row, and it only touches listings that exist
and are not already withdrawn, so it is safe to re-run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url

_WITHDRAW_SQL = """
    UPDATE listings AS l
    SET status = 'Withdrawn', expired_at = now()
    FROM feed_sources AS f
    WHERE l.feed_source_id = f.id
      AND f.code = %(code)s
      AND l.vendor_listing_id = ANY(%(ids)s)
      AND l.status <> 'Withdrawn'
"""

_PRESENT_SQL = """
    SELECT count(*) AS n
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %(code)s AND l.vendor_listing_id = ANY(%(ids)s)
"""


@dataclass(frozen=True, slots=True)
class WithdrawResult:
    requested: int
    withdrawn: int
    not_found: int


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def withdraw_listings(
    feed_source_code: str,
    vendor_listing_ids: Iterable[str],
    *,
    connect: Callable[[], psycopg.Connection] | None = None,
    dry_run: bool = False,
) -> WithdrawResult:
    """Mark the given feed's listings ``Withdrawn``. Idempotent; never deletes."""
    ids = sorted({str(v) for v in vendor_listing_ids if str(v).strip()})
    if not ids:
        return WithdrawResult(requested=0, withdrawn=0, not_found=0)

    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            params = {"code": feed_source_code, "ids": ids}
            cur.execute(_PRESENT_SQL, params)
            present = cur.fetchone()["n"]
            if dry_run:
                withdrawn = present
            else:
                cur.execute(_WITHDRAW_SQL, params)
                withdrawn = cur.rowcount
        return WithdrawResult(
            requested=len(ids), withdrawn=withdrawn, not_found=len(ids) - present
        )
    finally:
        conn.close()
