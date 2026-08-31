"""PropertyEngine adapter run — fetch (or read a file), decode, validate, map, import.

The feed is a single full-resend file (the Gumtree Pro standard template). There
is no delta endpoint and no deletion signal anywhere in the schema, so a listing
that stops appearing is caught by per-vendor reconciliation
(:func:`iol_importers.lifecycle.withdraw_missing`) — allowed whenever the pull
produced a non-empty id set (a corrupt body raises before this point; an empty set
is refused downstream), and skippable with ``--no-reconcile``. A stale listing
reconciliation somehow misses is still caught by the ``iol-expire-listings`` sweep.

Photos stay hotlinked (``primary_image_url`` + ``listing_media`` rows). Nothing in
this vendor's terms requires re-hosting — only Entegral's do.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_missing
from iol_importers.listings.importer import import_listings

from .client import PropertyEngineClient
from .decode import parse_feed
from .map import to_import_record
from .validate import run_warnings

logger = logging.getLogger("iol_importers.propertyengine")

_FEED = "propertyengine"


@dataclass(frozen=True, slots=True)
class PropertyEngineRunResult:
    counts: RunCounts
    mode: str
    source: str
    records_in_feed: int
    convention_warnings: dict[str, int]
    media_rows: int
    withdrawn: int
    reconciled: bool


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


# Reconciliation withdraws every stored listing absent from this pull. The
# catastrophic case — withdrawing a whole book because the feed came back empty or
# corrupt — is already blocked upstream: a malformed body raises in `parse_feed`
# before any import, and `withdraw_missing` itself refuses an empty id set. That
# leaves only the residual risk of a silently truncated but well-formed document,
# the same risk Entegral's per-office snapshot reconciliation accepts. Per-record
# validation failures (a bad Type, a malformed date) are the feed working as
# designed, not corruption, so they do not gate reconciliation.
def _reconcile_is_safe(seen_vids: list[str]) -> bool:
    return bool(seen_vids)


_SELECT_IDS = """
    SELECT l.id AS id, l.vendor_listing_id AS vid
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
"""


def run(
    *,
    feed_source_code: str = _FEED,
    file: str | None = None,
    max_listings: int | None = None,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    client: PropertyEngineClient | None = None,
) -> PropertyEngineRunResult:
    own_client = client is None
    client = client or PropertyEngineClient()
    try:
        if file is not None:
            body, content_type, source = client.read_file(file), None, f"file:{file}"
        else:
            body, content_type = client.fetch()
            source = "url"

        raw_records = parse_feed(body, content_type)
        if max_listings is not None:
            raw_records = raw_records[:max_listings]

        warnings = run_warnings(raw_records)
        for rule, count in warnings.items():
            if count:
                logger.warning(
                    "propertyengine: %d/%d records breach convention %r "
                    "(logged, not rejected)",
                    count,
                    len(raw_records),
                    rule,
                )

        mapped = [to_import_record(r) for r in raw_records]
        records = [rec for rec, _ in mapped]
        photos_by_vid = {
            rec["vendor_listing_id"]: urls
            for rec, urls in mapped
            if rec.get("vendor_listing_id") and urls
        }

        base = PropertyEngineRunResult(
            counts=RunCounts(seen=len(records)),
            mode="dry-run" if dry_run else "sync",
            source=source,
            records_in_feed=len(raw_records),
            convention_warnings=warnings,
            media_rows=0,
            withdrawn=0,
            reconciled=False,
        )
        if dry_run:
            return base

        counts = import_listings(
            records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"propertyengine:{source}",
        )

        media_rows = _sync_media(feed_source_code, photos_by_vid, connect)

        withdrawn = 0
        reconciled = False
        seen_vids = [r["vendor_listing_id"] for r in records if r.get("vendor_listing_id")]
        if reconcile and _reconcile_is_safe(seen_vids):
            withdrawn = withdraw_missing(
                feed_source_code, seen_vids, connect=connect
            ).withdrawn
            reconciled = True

        return PropertyEngineRunResult(
            counts=counts,
            mode="sync",
            source=source,
            records_in_feed=len(raw_records),
            convention_warnings=warnings,
            media_rows=media_rows,
            withdrawn=withdrawn,
            reconciled=reconciled,
        )
    finally:
        if own_client:
            client.close()


def _sync_media(
    feed_source_code: str,
    photos_by_vid: dict[str, list[str]],
    connect: Callable[[], psycopg.Connection] | None,
) -> int:
    """Upsert hotlinked ``listing_media`` (media_type 'Photo') for every imported
    listing, pruning URLs the feed no longer carries. Photos are not re-hosted."""
    if not photos_by_vid:
        return 0
    conn = (connect or _default_connect)()
    written = 0
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT_IDS, (feed_source_code, list(photos_by_vid)))
            rows = cur.fetchall()
        conn.rollback()
        for row in rows:
            urls = photos_by_vid.get(row["vid"]) or []
            if not urls:
                continue
            with conn.transaction():
                mc = conn.cursor(row_factory=dict_row)
                for order, url in enumerate(urls):
                    mc.execute(
                        """
                        INSERT INTO listing_media (listing_id, media_type, url, display_order)
                        VALUES (%s, 'Photo', %s, %s)
                        ON CONFLICT (listing_id, url)
                        DO UPDATE SET display_order = EXCLUDED.display_order
                        """,
                        (row["id"], url, order),
                    )
                    written += 1
                mc.execute(
                    """
                    DELETE FROM listing_media
                    WHERE listing_id = %s AND media_type = 'Photo' AND NOT (url = ANY(%s))
                    """,
                    (row["id"], urls),
                )
    finally:
        conn.close()
    return written


def format_result(result: PropertyEngineRunResult) -> str:
    c = result.counts
    lines = [
        f"mode                {result.mode}",
        f"source              {result.source}",
        f"records in feed     {result.records_in_feed}",
        f"  inserted          {c.inserted}",
        f"  updated           {c.updated}",
        f"  failed            {c.failed}",
        f"listing_media rows  {result.media_rows}",
        f"withdrawn (reconcile) {result.withdrawn}" + ("" if result.reconciled else "  (skipped)"),
    ]
    for rule, count in result.convention_warnings.items():
        if count:
            lines.append(f"warning: {rule}  {count} records (logged, not rejected)")
    return "\n".join(lines)
