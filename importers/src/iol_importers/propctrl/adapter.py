"""Adapter run — pull the PropCtrl change feed, filter it, feed the importer.

Flow:

1. Resolve ``from_date``: explicit argument, else the persisted checkpoint, else
   a documented default.
2. ``fetch_changes(from_date)`` — one delta response, keep its ``nextFromDate``.
3. ``Removed`` change items are skipped (the importer has no withdraw path);
   ``New`` / ``Modified`` ids are de-duplicated, newest change kept.
4. ``max_listings`` bounds the run.
5. Fetch listings ten ids at a time; drop anything whose ``listingStatus`` is not
   ``Active`` (counted separately).
6. Batch-fetch the referenced suburbs / agencies / branches / agents.
7. Stream the mapped records through one ``import_listings`` call.
8. Advance the checkpoint only when the whole change set was processed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from iol_importers.feeds.run import RunCounts
from iol_importers.listings.importer import import_listings

from .client import PropctrlClient
from .map import to_import_record

# The earliest data worth pulling if there is no checkpoint and no --from-date.
DEFAULT_FROM_DATE = "2020-01-01T00:00:00Z"

_ACTIVE = "Active"
_REMOVED = "Removed"


@dataclass(frozen=True, slots=True)
class PropctrlRunResult:
    counts: RunCounts
    from_date: str
    next_from_date: str
    changes_seen: int
    removed_skipped: int
    inactive_skipped: int
    checkpoint_written: bool


def _candidate_ids(items: list[dict]) -> tuple[list[int], dict[int, str], int]:
    """(ordered New/Modified ids, id -> latest changeType, removed count)."""
    removed = 0
    latest: dict[int, tuple[str, str]] = {}  # id -> (changeDate, changeType)
    for item in items:
        listing_id = item.get("id")
        change_type = item.get("changeType")
        if listing_id is None:
            continue
        if change_type == _REMOVED:
            removed += 1
            continue
        change_date = str(item.get("changeDate") or "")
        if listing_id not in latest or change_date >= latest[listing_id][0]:
            latest[listing_id] = (change_date, str(change_type))
    ids = list(latest.keys())
    return ids, {i: latest[i][1] for i in ids}, removed


def run(
    *,
    feed_source_code: str,
    from_date: str | None = None,
    max_listings: int | None = None,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    write_checkpoint: bool = True,
    client: PropctrlClient | None = None,
) -> PropctrlRunResult:
    own_client = client is None
    client = client or PropctrlClient()
    try:
        resolved_from = from_date or client.load_checkpoint() or DEFAULT_FROM_DATE
        items, next_from_date = client.fetch_changes(resolved_from)

        ids, change_type_by_id, removed_skipped = _candidate_ids(items)
        bounded = ids if max_listings is None else ids[:max_listings]
        complete = len(bounded) == len(ids)

        listings = list(client.iter_listings(bounded))
        active = [x for x in listings if x.get("listingStatus") == _ACTIVE]
        inactive_skipped = len(listings) - len(active)

        suburb_ids = {x["suburbId"] for x in active if x.get("suburbId") is not None}
        agency_ids = {x["agencyId"] for x in active if x.get("agencyId") is not None}
        branch_ids = {x["branchId"] for x in active if x.get("branchId") is not None}
        agent_ids = {a for x in active for a in (x.get("agentIds") or [])}
        suburbs = client.get_suburbs(suburb_ids) if suburb_ids else {}
        agencies = client.get_agencies(agency_ids) if agency_ids else {}
        branches = client.get_branches(branch_ids) if branch_ids else {}
        agents = client.get_agents(agent_ids) if agent_ids else {}

        records = [
            to_import_record(
                x,
                suburbs=suburbs,
                agencies=agencies,
                branches=branches,
                agents=agents,
                change_type=change_type_by_id.get(x.get("listingId")),
            )
            for x in active
        ]
        counts = import_listings(
            records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"propctrl:{resolved_from}",
        )

        checkpoint_written = False
        if write_checkpoint and complete and counts.failed == 0:
            client.save_checkpoint(next_from_date)
            checkpoint_written = True

        return PropctrlRunResult(
            counts=counts,
            from_date=resolved_from,
            next_from_date=next_from_date,
            changes_seen=len(items),
            removed_skipped=removed_skipped,
            inactive_skipped=inactive_skipped,
            checkpoint_written=checkpoint_written,
        )
    finally:
        if own_client:
            client.close()


def format_result(result: PropctrlRunResult) -> str:
    c = result.counts
    return "\n".join(
        [
            f"from_date          {result.from_date}",
            f"next_from_date     {result.next_from_date}"
            + ("  (checkpoint written)" if result.checkpoint_written else ""),
            f"changes seen       {result.changes_seen}",
            f"removed skipped    {result.removed_skipped}",
            f"inactive skipped   {result.inactive_skipped}",
            f"listings seen      {c.seen}",
            f"  inserted         {c.inserted}",
            f"  updated          {c.updated}",
            f"  failed           {c.failed}",
        ]
    )
