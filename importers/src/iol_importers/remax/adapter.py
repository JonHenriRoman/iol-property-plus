"""RE/MAX adapter run — the three sync paths.

* **full** — every agent's listings via ``/agents-page`` (the only paginated path
  that returns the full listing shape).
* **incremental** (default) — ``/lists-pagenate`` since the checkpoint, then
  ``/listing`` per changed id for the full shape.
* **deleted** — ``/lists_deleted`` → ``lifecycle.withdraw_listings`` (soft-delete).

``date_last_updated`` is compared against ``listings.last_updated_by_vendor_at``
so an unchanged record is skipped, not re-upserted. The checkpoint (the run's
start time) advances only after a complete, zero-failure run.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_listings
from iol_importers.listings.importer import import_listings

from .client import RemaxClient
from .map import to_import_record

DEFAULT_START_DATE = "2020-01-01 00:00:00"

Mode = str  # "incremental" | "full"


@dataclass(frozen=True, slots=True)
class RemaxRunResult:
    counts: RunCounts
    mode: str
    start_date: str | None
    checkpoint_written: bool
    agents_seen: int = 0
    pages_fetched: int = 0
    changed_seen: int = 0
    skipped_unchanged: int = 0
    withdrawn: int = 0
    withdraw_not_found: int = 0
    extras: dict[str, int] = field(default_factory=dict)


def _parse_ts(value: object) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _stored_updated_at(
    feed_source_code: str,
    vendor_ids: list[str],
    connect: Callable[[], psycopg.Connection] | None,
) -> dict[str, dt.datetime | None]:
    if not vendor_ids:
        return {}
    conn = (connect or _default_connect)()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT l.vendor_listing_id AS vid, l.last_updated_by_vendor_at AS ts
                FROM listings AS l
                JOIN feed_sources AS f ON f.id = l.feed_source_id
                WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
                """,
                (feed_source_code, vendor_ids),
            )
            return {row["vid"]: row["ts"] for row in cur.fetchall()}
    finally:
        conn.close()


def _is_unchanged(feed_ts: object, stored_ts: dt.datetime | None) -> bool:
    if stored_ts is None:
        return False
    parsed = _parse_ts(feed_ts)
    return parsed is not None and parsed <= stored_ts


def _dedupe_latest(items: list[dict], id_key: str, ts_key: str) -> list[dict]:
    best: dict[str, dict] = {}
    for item in items:
        vid = str(item.get(id_key))
        cur = best.get(vid)
        if cur is None or str(item.get(ts_key) or "") >= str(cur.get(ts_key) or ""):
            best[vid] = item
    return list(best.values())


def _run_deleted(
    client: RemaxClient,
    feed_source_code: str,
    *,
    connect: Callable[[], psycopg.Connection] | None,
    max_pages: int | None,
) -> tuple[int, int]:
    ids = [
        str(item["property_id"])
        for item in client.iter_deleted_listings(max_pages=max_pages)
        if item.get("property_id") is not None
    ]
    result = withdraw_listings(feed_source_code, ids, connect=connect)
    return result.withdrawn, result.not_found


def run(
    *,
    feed_source_code: str,
    mode: Mode = "incremental",
    start_date: str | None = None,
    max_pages: int | None = None,
    max_agents: int | None = None,
    with_deleted: bool = True,
    deleted_only: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    write_checkpoint: bool = True,
    client: RemaxClient | None = None,
) -> RemaxRunResult:
    own_client = client is None
    client = client or RemaxClient()
    run_started = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
    try:
        if deleted_only:
            withdrawn, not_found = _run_deleted(
                client, feed_source_code, connect=connect, max_pages=max_pages
            )
            return RemaxRunResult(
                counts=RunCounts(),
                mode="deleted",
                start_date=None,
                checkpoint_written=False,
                withdrawn=withdrawn,
                withdraw_not_found=not_found,
            )

        agents_seen = pages_fetched = 0
        if mode == "full":
            raw_items, agents_seen, pages_fetched = _collect_full(client, max_pages, max_agents)
            resolved_start = None
        else:
            resolved_start = start_date or client.load_checkpoint() or DEFAULT_START_DATE
            thin, pages_fetched = _collect_incremental(client, resolved_start, max_pages)
            raw_items = thin

        raw_items = _dedupe_latest(raw_items, "property_id", "date_last_updated")
        changed_seen = len(raw_items)

        vendor_ids = [str(x["property_id"]) for x in raw_items]
        stored = _stored_updated_at(feed_source_code, vendor_ids, connect)
        fresh = [
            x
            for x in raw_items
            if not _is_unchanged(x.get("date_last_updated"), stored.get(str(x["property_id"])))
        ]
        skipped_unchanged = changed_seen - len(fresh)

        records = list(_to_records(client, fresh, mode))
        counts = import_listings(
            records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"remax:{mode}:{resolved_start or 'full'}",
        )

        withdrawn = not_found = 0
        if with_deleted:
            withdrawn, not_found = _run_deleted(
                client, feed_source_code, connect=connect, max_pages=max_pages
            )

        complete = max_pages is None and max_agents is None
        checkpoint_written = False
        if write_checkpoint and complete and counts.failed == 0 and mode == "incremental":
            client.save_checkpoint(run_started)
            checkpoint_written = True

        return RemaxRunResult(
            counts=counts,
            mode=mode,
            start_date=resolved_start,
            checkpoint_written=checkpoint_written,
            agents_seen=agents_seen,
            pages_fetched=pages_fetched,
            changed_seen=changed_seen,
            skipped_unchanged=skipped_unchanged,
            withdrawn=withdrawn,
            withdraw_not_found=not_found,
        )
    finally:
        if own_client:
            client.close()


def _collect_full(
    client: RemaxClient, max_pages: int | None, max_agents: int | None
) -> tuple[list[dict], int, int]:
    agent_ids = client.list_agent_ids()
    if max_agents is not None:
        agent_ids = agent_ids[:max_agents]
    items: list[dict] = []
    pages = 0
    for agent_id in agent_ids:
        before = len(items)
        for prop in client.iter_agent_properties(agent_id, max_pages=max_pages):
            items.append(prop)
        pages += max(1, -(-(len(items) - before) // 15))  # approx pages fetched
    return items, len(agent_ids), pages


def _collect_incremental(
    client: RemaxClient, start_date: str, max_pages: int | None
) -> tuple[list[dict], int]:
    items = list(client.iter_changed_listings(start_date, max_pages=max_pages))
    pages = max(1, -(-len(items) // 1000)) if items else 0
    return items, pages


def _to_records(client: RemaxClient, items: list[dict], mode: str):
    for item in items:
        if mode == "full":
            yield to_import_record(item)
            continue
        detail = client.get_listing(item["property_id"])
        if detail is not None:
            yield to_import_record(detail)


def format_result(result: RemaxRunResult) -> str:
    c = result.counts
    lines = [
        f"mode               {result.mode}",
        f"start_date         {result.start_date or '(full)'}"
        + ("  (checkpoint written)" if result.checkpoint_written else ""),
    ]
    if result.mode == "full":
        lines.append(f"agents seen        {result.agents_seen}")
    lines += [
        f"pages fetched      {result.pages_fetched}",
        f"changed seen       {result.changed_seen}",
        f"skipped unchanged  {result.skipped_unchanged}",
        f"listings seen      {c.seen}",
        f"  inserted         {c.inserted}",
        f"  updated          {c.updated}",
        f"  failed           {c.failed}",
        f"withdrawn (soft)   {result.withdrawn}",
        f"withdraw not found {result.withdraw_not_found}",
    ]
    return "\n".join(lines)
