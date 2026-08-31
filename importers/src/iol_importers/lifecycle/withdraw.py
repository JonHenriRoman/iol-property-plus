"""Soft-delete listings a feed has removed.

Most feeds never send a delete — a withdrawn listing just stops appearing, and
``expire_listings`` catches it once ``expires_at`` passes. Two cases need a
prompt withdraw:

* :func:`withdraw_listings` — the feed sends an explicit deletion *list*
  (RE/MAX's ``/lists_deleted``): mark exactly those vendor ids ``Withdrawn``.
* :func:`withdraw_missing` — the feed sends a full *snapshot* of a scope and
  anything absent from it is gone (Entegral's per-office ``officelistings``):
  mark every row in the scope whose vendor id was *not* in the snapshot.

Neither ever deletes a row, both only touch listings that are not already
withdrawn, and both are safe to re-run.
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


_MISSING_COUNT_SQL = """
    SELECT count(*) AS n
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %(code)s
      AND l.status <> 'Withdrawn'
      AND NOT (l.vendor_listing_id = ANY(%(seen)s))
      {scope}
"""

_MISSING_WITHDRAW_SQL = """
    UPDATE listings AS l
    SET status = 'Withdrawn', expired_at = now()
    FROM feed_sources AS f
    WHERE l.feed_source_id = f.id
      AND f.code = %(code)s
      AND l.status <> 'Withdrawn'
      AND NOT (l.vendor_listing_id = ANY(%(seen)s))
      {scope}
"""

_SCOPE_CLAUSE = "AND l.raw_data ->> %(scope_key)s = %(scope_value)s"


def withdraw_missing(
    feed_source_code: str,
    seen_vendor_listing_ids: Iterable[str],
    *,
    raw_scope: tuple[str, str] | None = None,
    connect: Callable[[], psycopg.Connection] | None = None,
    dry_run: bool = False,
) -> WithdrawResult:
    """Withdraw every non-withdrawn listing in ``feed_source_code`` (optionally
    narrowed to ``raw_data ->> raw_scope[0] = raw_scope[1]``) whose vendor id is
    not in ``seen_vendor_listing_ids``.

    Raises ``ValueError`` on an empty ``seen`` set — a snapshot that came back
    empty must never withdraw the whole scope. Idempotent; never deletes.
    """
    seen = sorted({str(v) for v in seen_vendor_listing_ids if str(v).strip()})
    if not seen:
        raise ValueError(
            "withdraw_missing refuses an empty seen set — an empty snapshot must "
            "not withdraw every listing in scope"
        )

    scope = _SCOPE_CLAUSE if raw_scope is not None else ""
    params: dict[str, object] = {"code": feed_source_code, "seen": seen}
    if raw_scope is not None:
        params["scope_key"], params["scope_value"] = raw_scope

    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            if dry_run:
                cur.execute(_MISSING_COUNT_SQL.format(scope=scope), params)
                withdrawn = cur.fetchone()["n"]
            else:
                cur.execute(_MISSING_WITHDRAW_SQL.format(scope=scope), params)
                withdrawn = cur.rowcount
        return WithdrawResult(requested=len(seen), withdrawn=withdrawn, not_found=0)
    finally:
        conn.close()
