"""MyRoof adapter run — fetch (or read a file), parse with the shared bracket-KV
parser, map, import, hotlink media, reconcile.

The feed is a full resend of one franchise's book with no delete signal, so a
listing that stops appearing is caught by
:func:`iol_importers.lifecycle.withdraw.withdraw_missing` (which refuses an empty
seen set — a broken fetch cannot withdraw the whole book) and, failing that, the
``iol-expire-listings`` sweep.

Agency / agent rows are created through the Step 14 resolvers from the record
fields (single-brand feed, one agent per listing) — no separate reference pass.
Photos are hotlinked, not re-hosted; MyRoof imposes no such term.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from iol_importers import bracket_kv
from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_missing
from iol_importers.listings.importer import import_listings

from .client import MyroofClient
from .map import to_import_record
from .source import resolve_source

logger = logging.getLogger("iol_importers.myroof")

_FEED = "myroof"


@dataclass(frozen=True, slots=True)
class MyroofRunResult:
    counts: RunCounts
    source: str  # "myroof:<feed_source_code>" — never the token
    records_in_feed: int
    media_rows: int
    withdrawn: int
    reconciled: bool
    agent_programs: dict[str, int]
    raw_data_keys: dict[str, int]
    dry_run: bool


@dataclass
class _Collected:
    records: list[dict] = field(default_factory=list)
    photos_by_vid: dict[str, list[str]] = field(default_factory=dict)
    agent_programs: Counter = field(default_factory=Counter)
    raw_data_keys: Counter = field(default_factory=Counter)


def _collect(records: list[bracket_kv.BracketRecord]) -> _Collected:
    c = _Collected()
    for rec in records:
        mapped, images = to_import_record(rec)
        c.records.append(mapped)
        program = mapped.get("myroof_agent_program")
        if program:
            c.agent_programs[program] += 1
        for key in mapped:
            if key.startswith("myroof_"):
                c.raw_data_keys[key] += 1
        vid = mapped.get("vendor_listing_id")
        if vid and images and not mapped.get("__validation_error__"):
            c.photos_by_vid[vid] = images
    return c


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


_SELECT_LISTING_IDS = """
    SELECT l.id AS id, l.vendor_listing_id AS vid
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
"""


def run(
    *,
    feed_source_code: str = _FEED,
    token: str | None = None,
    file: str | None = None,
    max_listings: int | None = None,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    client: MyroofClient | None = None,
) -> MyroofRunResult:
    if token is None and file is None:
        token = resolve_source(feed_source_code, connect=connect).token

    own_client = client is None
    client = client or MyroofClient()
    try:
        body = client.read_file(file) if file is not None else client.fetch(token or "")

        records = bracket_kv.parse(body)
        if max_listings is not None:
            records = records[:max_listings]

        col = _collect(records)
        base = {
            "source": f"myroof:{feed_source_code}",
            "records_in_feed": len(records),
            "agent_programs": dict(col.agent_programs),
            "raw_data_keys": dict(col.raw_data_keys),
        }

        if dry_run:
            return MyroofRunResult(
                counts=RunCounts(seen=len(col.records)),
                media_rows=0,
                withdrawn=0,
                reconciled=False,
                dry_run=True,
                **base,
            )

        counts = import_listings(
            col.records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"myroof:{feed_source_code}",
        )
        media_rows = _sync_media(feed_source_code, col.photos_by_vid, connect)

        withdrawn = 0
        reconciled = False
        seen_vids = [
            r["vendor_listing_id"]
            for r in col.records
            if r.get("vendor_listing_id") and not r.get("__validation_error__")
        ]
        if reconcile and seen_vids:
            withdrawn = withdraw_missing(feed_source_code, seen_vids, connect=connect).withdrawn
            reconciled = True

        return MyroofRunResult(
            counts=counts,
            media_rows=media_rows,
            withdrawn=withdrawn,
            reconciled=reconciled,
            dry_run=False,
            **base,
        )
    finally:
        if own_client:
            client.close()


def _sync_media(
    feed_source_code: str,
    photos_by_vid: dict[str, list[str]],
    connect: Callable[[], psycopg.Connection] | None,
) -> int:
    """Upsert hotlinked ``listing_media`` (media_type 'Photo'), pruning URLs the
    feed no longer carries. Photos are not re-hosted."""
    if not photos_by_vid:
        return 0
    conn = (connect or _default_connect)()
    written = 0
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT_LISTING_IDS, (feed_source_code, list(photos_by_vid)))
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


def format_result(result: MyroofRunResult) -> str:
    c = result.counts
    lines = [
        f"mode                 {'dry-run' if result.dry_run else 'sync'}",
        f"source               {result.source}",
        f"records in feed      {result.records_in_feed}",
        f"  seen               {c.seen}",
        f"  inserted           {c.inserted}",
        f"  updated            {c.updated}",
        f"  failed             {c.failed}",
        f"listing_media rows   {result.media_rows}",
        f"withdrawn (reconcile){result.withdrawn}" + ("" if result.reconciled else "  (skipped)"),
    ]
    if result.agent_programs:
        lines.append("repossession programs (Agent_Name):")
        for name, n in sorted(result.agent_programs.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {name}  {n}")
    if result.raw_data_keys:
        lines.append("raw_data keys captured (unlisted feed fields):")
        for key, n in sorted(result.raw_data_keys.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {key}  {n}")
    return "\n".join(lines)
