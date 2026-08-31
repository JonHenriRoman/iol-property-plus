"""AllSA adapter run — fetch (or read a file), parse, map, enrich, import, reconcile.

The feed is a full resend of one agency's book with no delete signal, so a listing
that stops appearing is caught by :func:`iol_importers.lifecycle.withdraw.withdraw_missing`
(gated on a non-empty id set — an empty ``<Listings/>`` withdraws nothing) and,
failing that, the ``iol-expire-listings`` sweep.

Order of writes per run: offices/agents (so the importer's agency/agent resolvers
link to the enriched row, not a name-only stub) -> ``import_listings`` ->
hotlinked ``listing_media`` -> reconcile. Photos are not re-hosted; AllSA imposes
no such term.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from iol_importers.config import resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_missing
from iol_importers.listings.importer import import_listings

from .client import AllsaClient
from .features import parse_features
from .map import to_import_record
from .parse import parse_feed
from .reference import upsert_agency, upsert_agent
from .source import resolve_source

logger = logging.getLogger("iol_importers.allsa")

_FEED = "allsa"


@dataclass(frozen=True, slots=True)
class AllsaRunResult:
    counts: RunCounts
    agency_id: str
    source: str
    properties_in_feed: int
    branches: dict[str, int]
    agencies_upserted: int
    agents_upserted: int
    media_rows: int
    withdrawn: int
    reconciled: bool
    unknown_feature_tags: dict[str, int]
    duplicate_feature_elements: int
    dry_run: bool


@dataclass
class _Tally:
    agencies_upserted: int = 0
    agents_upserted: int = 0
    unknown_feature_tags: Counter = field(default_factory=Counter)


@dataclass
class _Collected:
    records: list[dict] = field(default_factory=list)
    photos_by_vid: dict[str, list[str]] = field(default_factory=dict)
    branches: dict[str, dict[str, str]] = field(default_factory=dict)
    agents: dict[str, dict[str, str]] = field(default_factory=dict)
    branch_counts: Counter = field(default_factory=Counter)
    unknown_feature_tags: Counter = field(default_factory=Counter)


def _collect(properties: list) -> _Collected:
    """One pass over the parsed properties: map each, and cache the per-branch and
    per-agent reference rows plus the unknown-feature tally."""
    c = _Collected()
    for prop in properties:
        record, photos = to_import_record(prop)
        c.records.append(record)

        branch_id = prop.fields.get("BranchId", "").strip()
        if branch_id:
            c.branch_counts[branch_id] += 1
            c.branches.setdefault(branch_id, dict(prop.fields))

        email = (prop.fields.get("Agent_Email") or "").strip().lower()
        if email:
            c.agents.setdefault(email, {**dict(prop.fields), "_branch_id": branch_id})

        for tag in parse_features(prop.features).unknown_tags:
            c.unknown_feature_tags[tag] += 1

        vid = record.get("vendor_listing_id")
        if vid and photos and not record.get("__validation_error__"):
            c.photos_by_vid[vid] = photos
    return c


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


def _feed_source_id(connect: Callable[[], psycopg.Connection] | None, code: str) -> int:
    conn = (connect or _default_connect)()
    try:
        row = conn.execute("SELECT id FROM feed_sources WHERE code = %s", (code,)).fetchone()
        conn.rollback()
        if row is None:
            raise RuntimeError(f"no feed_sources row with code {code!r} (seeded configuration)")
        return row["id"]
    finally:
        conn.close()


_SELECT_LISTING_IDS = """
    SELECT l.id AS id, l.vendor_listing_id AS vid
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
"""


def run(
    *,
    feed_source_code: str = _FEED,
    agency_id: str | None = None,
    file: str | None = None,
    max_listings: int | None = None,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    client: AllsaClient | None = None,
) -> AllsaRunResult:
    if agency_id is None and file is None:
        agency_id = resolve_source(feed_source_code, connect=connect).agency_id

    own_client = client is None
    client = client or AllsaClient()
    try:
        if file is not None:
            body, source = client.read_file(file), f"file:{file}"
        else:
            body, source = client.fetch(agency_id or ""), f"agencyid:{agency_id}"

        parsed = parse_feed(body)
        properties = parsed.properties
        if max_listings is not None:
            properties = properties[:max_listings]

        col = _collect(properties)
        tally = _Tally(unknown_feature_tags=col.unknown_feature_tags)
        base_kwargs = {
            "agency_id": str(agency_id or ""),
            "source": source,
            "properties_in_feed": len(properties),
            "branches": dict(col.branch_counts),
            "duplicate_feature_elements": parsed.duplicate_feature_elements,
            "unknown_feature_tags": dict(col.unknown_feature_tags),
        }

        if dry_run:
            return AllsaRunResult(
                counts=RunCounts(seen=len(col.records)),
                agencies_upserted=0,
                agents_upserted=0,
                media_rows=0,
                withdrawn=0,
                reconciled=False,
                dry_run=True,
                **base_kwargs,
            )

        _apply_refs(feed_source_code, connect, col.branches, col.agents, tally)

        counts = import_listings(
            col.records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"allsa:{agency_id}",
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

        return AllsaRunResult(
            counts=counts,
            agencies_upserted=tally.agencies_upserted,
            agents_upserted=tally.agents_upserted,
            media_rows=media_rows,
            withdrawn=withdrawn,
            reconciled=reconciled,
            dry_run=False,
            **base_kwargs,
        )
    finally:
        if own_client:
            client.close()


def _apply_refs(
    feed_source_code: str,
    connect: Callable[[], psycopg.Connection] | None,
    branches: dict[str, dict[str, str]],
    agents: dict[str, dict[str, str]],
    tally: _Tally,
) -> None:
    fsid = _feed_source_id(connect, feed_source_code)
    agency_id_by_branch: dict[str, str] = {}
    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            for branch_id, branch in branches.items():
                agency_id, created = upsert_agency(cur, fsid, branch)
                agency_id_by_branch[branch_id] = agency_id
                tally.agencies_upserted += 1 if created else 0
            for agent in agents.values():
                linked_agency = agency_id_by_branch.get(agent.get("_branch_id", ""))
                _, created = upsert_agent(cur, fsid, agent, linked_agency)
                tally.agents_upserted += 1 if created else 0
    finally:
        conn.close()


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


def format_result(result: AllsaRunResult) -> str:
    c = result.counts
    lines = [
        f"mode                 {'dry-run' if result.dry_run else 'sync'}",
        f"source               {result.source}",
        f"agency id            {result.agency_id}",
        f"properties in feed   {result.properties_in_feed}",
        f"  inserted           {c.inserted}",
        f"  updated            {c.updated}",
        f"  failed             {c.failed}",
        f"branches (BranchId)  {len(result.branches)}",
    ]
    for branch_id, n in sorted(result.branches.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {branch_id:>10}  {n}")
    lines += [
        f"agencies upserted    {result.agencies_upserted}",
        f"agents upserted      {result.agents_upserted}",
        f"listing_media rows   {result.media_rows}",
        f"withdrawn (reconcile){result.withdrawn}" + ("" if result.reconciled else "  (skipped)"),
        f"duplicate <Features> elements dropped  {result.duplicate_feature_elements}",
    ]
    if result.unknown_feature_tags:
        lines.append("unknown feature tags (kept in raw_data.allsa_features_extra):")
        for tag, n in sorted(result.unknown_feature_tags.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {tag}  {n}")
    return "\n".join(lines)
