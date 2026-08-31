"""Fusion adapter run — the snapshot / GetChanges drain loop.

First run (no saved ``commitToken`` and no snapshot in progress): ``RequestSnapshot``
then drain. Otherwise: ``GetChanges`` from the saved token. Each batch is applied
in full — AreaTree crosswalk, then Office/Agent upserts, then one
``import_listings`` for the batch's listings, then listing soft-deletes — and only
**then** is the new ``commitToken`` persisted, so a crash replays an unacknowledged
batch (every event is an idempotent upsert / soft-delete). ``BeginSnapshot`` …
``EndSnapshot`` may span many batches; after ``EndSnapshot`` a pass backfills
``suburb_id`` for listings whose AreaTree node arrived in a later batch.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_listings
from iol_importers.listings.importer import import_listings
from iol_importers.listings.resolve import resolve_suburb

from .areatree import AreaTree
from .client import FusionClient, FusionState, SnapshotState
from .map import to_import_record
from .parse import ChangesBatch, FusionException
from .reference import soft_delete, upsert_agency, upsert_agent

logger = logging.getLogger("iol_importers.fusion")

_FEED = "fusion"
_MAX_TOKEN_RECOVERIES = 5


@dataclass(frozen=True, slots=True)
class FusionRunResult:
    counts: RunCounts
    batches: int
    snapshot_seen: bool
    snapshot_completed: bool
    events_by_type: dict[str, int]
    events_by_object: dict[str, int]
    listings_withdrawn: int
    agencies_upserted: int
    agents_upserted: int
    refs_withdrawn: int
    suburbs_crosswalked: int
    suburbs_backfilled: int
    commit_token: str | None
    commit_token_advanced: bool
    dry_run: bool = False
    extras: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _Tally:
    events_by_type: dict[str, int] = field(default_factory=dict)
    events_by_object: dict[str, int] = field(default_factory=dict)
    agencies_upserted: int = 0
    agents_upserted: int = 0
    refs_withdrawn: int = 0
    listings_withdrawn: int = 0
    suburbs_crosswalked: int = 0
    suburbs_backfilled: int = 0
    counts: RunCounts = field(default_factory=RunCounts)

    def bump(self, kind: str, obj: str) -> None:
        self.events_by_type[kind] = self.events_by_type.get(kind, 0) + 1
        self.events_by_object[obj] = self.events_by_object.get(obj, 0) + 1


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _add(a: RunCounts, b: RunCounts) -> RunCounts:
    return RunCounts(
        seen=a.seen + b.seen,
        inserted=a.inserted + b.inserted,
        updated=a.updated + b.updated,
        skipped=a.skipped + b.skipped,
        expired=a.expired + b.expired,
        failed=a.failed + b.failed,
    )


def _feed_source_id(connect: Callable[[], psycopg.Connection] | None, code: str) -> int:
    conn = (connect or _default_connect)()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id FROM feed_sources WHERE code = %s", (code,))
            row = cur.fetchone()
        conn.rollback()
        if row is None:
            raise RuntimeError(f"no feed_sources row with code {code!r} (seeded configuration)")
        return row["id"]
    finally:
        conn.close()


def run(
    *,
    feed_source_code: str = _FEED,
    max_batches: int | None = None,
    force_snapshot: bool = False,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    write_state: bool = True,
    client: FusionClient | None = None,
) -> FusionRunResult:
    own_client = client is None
    client = client or FusionClient()
    try:
        return _drain(
            client,
            feed_source_code=feed_source_code,
            max_batches=max_batches,
            force_snapshot=force_snapshot,
            dry_run=dry_run,
            connect=connect,
            tracking_connect=tracking_connect,
            write_state=write_state and not dry_run,
        )
    finally:
        if own_client:
            client.close()


def _drain(
    client: FusionClient,
    *,
    feed_source_code: str,
    max_batches: int | None,
    force_snapshot: bool,
    dry_run: bool,
    connect: Callable[[], psycopg.Connection] | None,
    tracking_connect: Callable[[], psycopg.Connection] | None,
    write_state: bool,
) -> FusionRunResult:
    state = client.load_state()
    areatree = AreaTree.load(client.area_tree_path())
    developments: dict[str, dict[str, str]] = _load_developments(client.developments_path())
    office_names: dict[str, str] = {}
    agent_names: dict[str, str] = {}
    tally = _Tally()

    snapshot_types: tuple[str, ...] = state.snapshot.types
    if force_snapshot or (state.commit_token is None and not state.snapshot.in_progress):
        warning = client.request_snapshot()
        if warning:
            logger.info("fusion: RequestSnapshot warning=%s", warning)
        token: str | None = None
        snapshot_in_progress = True
        snapshot_seen = True
    else:
        token = state.commit_token
        snapshot_in_progress = state.snapshot.in_progress
        snapshot_seen = snapshot_in_progress

    snapshot_completed = False
    batches = 0
    recoveries = 0
    start_token = state.commit_token

    while max_batches is None or batches < max_batches:
        try:
            batch = client.get_changes(token)
        except FusionException as exc:
            if exc.type in ("InvalidCommitToken", "CommitTokenExpired"):
                recoveries += 1
                if recoveries > _MAX_TOKEN_RECOVERIES:
                    raise
                token = exc.attrib.get("commitToken") if exc.type == "InvalidCommitToken" else None
                logger.warning("fusion: %s — restarting from token=%r", exc.type, token)
                continue
            raise

        if batch.drained:
            break

        _apply_batch(
            batch,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            areatree=areatree,
            developments=developments,
            office_names=office_names,
            agent_names=agent_names,
            dry_run=dry_run,
            tally=tally,
        )

        token = batch.commit_token
        if batch.begin_snapshot is not None:
            snapshot_in_progress = True
            snapshot_seen = True
            snapshot_types = batch.begin_snapshot
        if batch.end_snapshot:
            snapshot_in_progress = False
            snapshot_completed = True

        if write_state:
            client.save_state(
                FusionState(
                    commit_token=token,
                    snapshot=SnapshotState(snapshot_in_progress, snapshot_types),
                    updated_at=dt.datetime.now(dt.UTC).isoformat(),
                )
            )
            areatree.save(client.area_tree_path())
            _save_developments(client.developments_path(), developments)

        if batch.end_snapshot and not dry_run:
            tally.suburbs_backfilled += _resolve_pending_suburbs(
                feed_source_code, areatree, connect
            )

        batches += 1
        if not snapshot_in_progress and batch.sync_events_count == 0:
            break

    return FusionRunResult(
        counts=tally.counts,
        batches=batches,
        snapshot_seen=snapshot_seen,
        snapshot_completed=snapshot_completed,
        events_by_type=dict(tally.events_by_type),
        events_by_object=dict(tally.events_by_object),
        listings_withdrawn=tally.listings_withdrawn,
        agencies_upserted=tally.agencies_upserted,
        agents_upserted=tally.agents_upserted,
        refs_withdrawn=tally.refs_withdrawn,
        suburbs_crosswalked=tally.suburbs_crosswalked,
        suburbs_backfilled=tally.suburbs_backfilled,
        commit_token=token,
        commit_token_advanced=token is not None and token != start_token,
        dry_run=dry_run,
        extras={"developments_seen": len(developments)},
    )


def _apply_batch(
    batch: ChangesBatch,
    *,
    feed_source_code: str,
    connect: Callable[[], psycopg.Connection] | None,
    tracking_connect: Callable[[], psycopg.Connection] | None,
    areatree: AreaTree,
    developments: dict[str, dict[str, str]],
    office_names: dict[str, str],
    agent_names: dict[str, str],
    dry_run: bool,
    tally: _Tally,
) -> None:
    listing_records: list[dict] = []
    listing_deletes: list[str] = []
    office_events: list[Element] = []
    agent_events: list[Element] = []
    office_deletes: list[str] = []
    agent_deletes: list[str] = []

    for event in batch.events:
        tally.bump(event.kind, event.object_type)
        if event.object_type == "AreaTree":
            if event.kind == "Delete":
                areatree.remove(event.element.tag, event.ref_id)
            else:
                tally.suburbs_crosswalked += areatree.apply_element(event.element)
        elif event.object_type == "Office":
            if event.kind == "Delete":
                if event.ref_id:
                    office_deletes.append(event.ref_id)
            else:
                office_events.append(event.element)
                office_names[event.element.get("id") or ""] = _office_label(event.element)
        elif event.object_type == "Agent":
            if event.kind == "Delete":
                if event.ref_id:
                    agent_deletes.append(event.ref_id)
            else:
                agent_events.append(event.element)
                agent_names[event.element.get("id") or ""] = _agent_label(event.element)
        elif event.object_type == "Development":
            if event.kind == "Delete":
                developments.pop(event.ref_id or "", None)
            else:
                developments[event.element.get("id") or ""] = dict(event.element.attrib)
        elif event.object_type == "Listing":
            if event.kind == "Delete":
                if event.ref_id:
                    listing_deletes.append(event.ref_id)
            else:
                record, _ = to_import_record(
                    event.element,
                    areatree=areatree,
                    event_timestamp=event.timestamp,
                    office_names=office_names,
                    agent_names=agent_names,
                )
                listing_records.append(record)

    if dry_run:
        tally.counts = _add(tally.counts, RunCounts(seen=len(listing_records)))
        return

    if office_events or agent_events or office_deletes or agent_deletes:
        _apply_refs(
            feed_source_code,
            connect,
            office_events,
            agent_events,
            office_deletes,
            agent_deletes,
            tally,
        )

    if listing_records:
        counts = import_listings(
            listing_records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"fusion:{batch.commit_token}",
        )
        tally.counts = _add(tally.counts, counts)

    if listing_deletes:
        result = withdraw_listings(feed_source_code, listing_deletes, connect=connect)
        tally.listings_withdrawn += result.withdrawn


def _apply_refs(
    feed_source_code: str,
    connect: Callable[[], psycopg.Connection] | None,
    office_events: list[Element],
    agent_events: list[Element],
    office_deletes: list[str],
    agent_deletes: list[str],
    tally: _Tally,
) -> None:
    fsid = _feed_source_id(connect, feed_source_code)
    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            for office in office_events:
                _, created = upsert_agency(cur, fsid, office)
                tally.agencies_upserted += 1 if created else 0
            for agent in agent_events:
                _, created = upsert_agent(cur, fsid, agent)
                tally.agents_upserted += 1 if created else 0
            for ref_id in office_deletes:
                tally.refs_withdrawn += 1 if soft_delete(cur, fsid, "Office", ref_id) else 0
            for ref_id in agent_deletes:
                tally.refs_withdrawn += 1 if soft_delete(cur, fsid, "Agent", ref_id) else 0
    finally:
        conn.close()


def _resolve_pending_suburbs(
    feed_source_code: str,
    areatree: AreaTree,
    connect: Callable[[], psycopg.Connection] | None,
) -> int:
    conn = (connect or _default_connect)()
    updated = 0
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT l.raw_data ->> 'fusion_suburb_id' AS sid
                FROM listings AS l
                JOIN feed_sources AS f ON f.id = l.feed_source_id
                WHERE f.code = %s AND l.suburb_id IS NULL
                  AND l.raw_data ->> 'fusion_suburb_id' IS NOT NULL
                """,
                (feed_source_code,),
            )
            pending = [row["sid"] for row in cur.fetchall()]
        conn.rollback()
        for sid in pending:
            name = areatree.suburb_name(sid)
            if not name:
                continue
            with conn.transaction():
                cur = conn.cursor(row_factory=dict_row)
                suburb_id = resolve_suburb(cur, name)
                if suburb_id is None:
                    continue
                cur.execute(
                    """
                    UPDATE listings AS l
                    SET suburb_id = %s
                    FROM feed_sources AS f
                    WHERE l.feed_source_id = f.id AND f.code = %s
                      AND l.suburb_id IS NULL
                      AND l.raw_data ->> 'fusion_suburb_id' = %s
                    """,
                    (suburb_id, feed_source_code, sid),
                )
                updated += cur.rowcount
        return updated
    finally:
        conn.close()


def _office_label(office: Element) -> str:
    bits = [office.get("agency"), office.get("branch")]
    return " — ".join(b.strip() for b in bits if b and b.strip()) or (office.get("id") or "")


def _agent_label(agent: Element) -> str:
    bits = [agent.get("firstName"), agent.get("surname")]
    name = " ".join(b.strip() for b in bits if b and b.strip())
    return name or (agent.get("title") or agent.get("id") or "")


def _load_developments(path: Path) -> dict[str, dict[str, str]]:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def _save_developments(path: Path, developments: dict[str, dict[str, str]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(developments, sort_keys=True, indent=0))


def format_result(result: FusionRunResult) -> str:
    c = result.counts
    by_type = ", ".join(f"{k}={v}" for k, v in sorted(result.events_by_type.items())) or "(none)"
    by_obj = ", ".join(f"{k}={v}" for k, v in sorted(result.events_by_object.items())) or "(none)"
    lines = [
        f"mode                {'dry-run' if result.dry_run else 'sync'}",
        f"batches             {result.batches}",
        f"snapshot            seen={result.snapshot_seen} completed={result.snapshot_completed}",
        f"events by type      {by_type}",
        f"events by object    {by_obj}",
        f"listings seen       {c.seen}",
        f"  inserted          {c.inserted}",
        f"  updated           {c.updated}",
        f"  failed            {c.failed}",
        f"listings withdrawn  {result.listings_withdrawn}",
        f"agencies created    {result.agencies_upserted}",
        f"agents created      {result.agents_upserted}",
        f"refs soft-deleted   {result.refs_withdrawn}",
        f"suburbs crosswalked {result.suburbs_crosswalked}",
        f"suburbs backfilled  {result.suburbs_backfilled}",
        f"commit token        {result.commit_token or '(none)'}"
        + ("  (advanced)" if result.commit_token_advanced else ""),
    ]
    return "\n".join(lines)
