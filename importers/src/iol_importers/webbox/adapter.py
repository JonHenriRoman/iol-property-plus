"""Webbox adapter run — fetch (or read a file), stream-parse, enrich, import, reconcile.

The feed is a full resend of one site's book with no delete signal, so a listing
that stops appearing is caught by
:func:`iol_importers.lifecycle.withdraw.withdraw_missing` (gated on a non-empty id
set — an empty document withdraws nothing) and, failing that, the
``iol-expire-listings`` sweep.

Order of writes per run mirrors the AllSA adapter: agencies/agents first (so the
importer's resolvers link to the enriched row, not a name-only stub) ->
``import_listings`` -> hotlinked ``listing_media`` -> reconcile. Photos are not
re-hosted.

The parser reports which outer XML form the feed actually used
(``<agencies>/<agency>/<properties>/<property>`` vs a bare ``<property>`` root vs
a consecutive stream); it is surfaced on :attr:`WebboxRunResult.outer_form`.
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

from .client import WebboxClient
from .features import parse_features
from .map import to_import_record
from .parse import parse_feed
from .reference import upsert_agency, upsert_agent
from .source import resolve_source

logger = logging.getLogger("iol_importers.webbox")

_FEED = "webbox"

_KNOWN_TYPES_LOWER: frozenset[str] = frozenset(
    {
        "house",
        "apartment",
        "townhouse",
        "vacant land",
        "cluster",
        "farm",
        "apartment block",
        "office",
        "workshop",
        "residential estate",
        "development",
        "flat apartment",
        "commercial",
        "industrial",
    }
)


@dataclass(frozen=True, slots=True)
class WebboxRunResult:
    counts: RunCounts
    source: str  # "webbox:<feed_source_code>" — never the key
    outer_form: str
    agencies_seen: int
    properties_in_feed: int
    listing_types: dict[str, int]
    countries: dict[str, int]
    non_zar_rejected: int
    agencies_upserted: int
    agents_upserted: int
    agent_counts: dict[str, int]
    titles_synthesized: int
    unknown_feature_tags: dict[str, int]
    unmapped_property_types: dict[str, int]
    media_rows: int
    withdrawn: int
    reconciled: bool
    raw_data_keys: dict[str, int]
    dry_run: bool


@dataclass
class _Collected:
    records: list[dict] = field(default_factory=list)
    photos_by_vid: dict[str, list[str]] = field(default_factory=dict)
    agencies: dict[str, dict[str, str]] = field(default_factory=dict)
    agents: dict[str, dict[str, str]] = field(default_factory=dict)
    listing_types: Counter = field(default_factory=Counter)
    countries: Counter = field(default_factory=Counter)
    agent_counts: Counter = field(default_factory=Counter)
    unknown_feature_tags: Counter = field(default_factory=Counter)
    unmapped_property_types: Counter = field(default_factory=Counter)
    raw_data_keys: Counter = field(default_factory=Counter)
    titles_synthesized: int = 0
    non_zar_rejected: int = 0


def _agent_bucket(n: int) -> str:
    return "3+" if n >= 3 else str(n)


def _collect(properties: list) -> _Collected:
    c = _Collected()
    for prop in properties:
        record, photos = to_import_record(prop)
        c.records.append(record)

        agency_id = (prop.agency.get("id") or "").strip()
        if agency_id:
            c.agencies.setdefault(agency_id, dict(prop.agency))
        for agent in prop.agents:
            aid = (agent.get("agent-id") or "").strip()
            if aid:
                c.agents.setdefault(aid, {**agent, "_agency_id": agency_id})

        lt = (prop.fields.get("listing-type") or "").strip()
        if lt:
            c.listing_types[lt] += 1
        c.countries[
            (prop.nested.get("location", {}).get("country") or "").strip() or "(unset)"
        ] += 1
        c.agent_counts[_agent_bucket(len(prop.agents))] += 1

        if not (prop.fields.get("heading") or "").strip() and record.get("title"):
            c.titles_synthesized += 1
        err = record.get("__validation_error__") or ""
        if err.startswith("non-ZAR"):
            c.non_zar_rejected += 1

        pt = record.get("property_type")
        if pt and pt.lower() not in _KNOWN_TYPES_LOWER:
            c.unmapped_property_types[pt] += 1
        for tag in parse_features(prop.features).unknown_tags:
            c.unknown_feature_tags[tag] += 1
        for key in record:
            if key.startswith("webbox_"):
                c.raw_data_keys[key] += 1

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


def _apply_refs(
    feed_source_code: str,
    connect: Callable[[], psycopg.Connection] | None,
    agencies: dict[str, dict[str, str]],
    agents: dict[str, dict[str, str]],
) -> tuple[int, int]:
    """Upsert enriched agency + agent rows before ``import_listings`` runs.
    Returns ``(agencies_created, agents_created)``."""
    if not agencies and not agents:
        return 0, 0
    fsid = _feed_source_id(connect, feed_source_code)
    agencies_created = 0
    agents_created = 0
    agency_id_by_vendor: dict[str, str] = {}
    conn = (connect or _default_connect)()
    try:
        with conn.transaction():
            cur = conn.cursor(row_factory=dict_row)
            for vendor_id, agency in agencies.items():
                canonical_id, created = upsert_agency(cur, fsid, agency)
                agency_id_by_vendor[vendor_id] = canonical_id
                agencies_created += 1 if created else 0
            for agent in agents.values():
                linked = agency_id_by_vendor.get(agent.get("_agency_id", ""))
                _, created = upsert_agent(cur, fsid, agent, linked)
                agents_created += 1 if created else 0
    finally:
        conn.close()
    return agencies_created, agents_created


def run(
    *,
    feed_source_code: str = _FEED,
    siteid: str | None = None,
    securitykey: str | None = None,
    base_url: str | None = None,
    file: str | None = None,
    max_listings: int | None = None,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    client: WebboxClient | None = None,
) -> WebboxRunResult:
    if file is None and (siteid is None or securitykey is None):
        src = resolve_source(feed_source_code, connect=connect)
        siteid, securitykey = src.siteid, src.securitykey
        base_url = base_url or src.base_url

    own_client = client is None
    client = client or WebboxClient(base_url=base_url or "")
    try:
        body = (
            client.read_file(file)
            if file is not None
            else client.fetch(siteid or "", securitykey or "")
        )
        parsed = parse_feed(body)
        properties = parsed.properties
        if max_listings is not None:
            properties = properties[:max_listings]

        col = _collect(properties)
        base = {
            "source": f"webbox:{feed_source_code}",
            "outer_form": parsed.outer_form,
            "agencies_seen": parsed.agencies_seen,
            "properties_in_feed": len(properties),
            "listing_types": dict(col.listing_types),
            "countries": dict(col.countries),
            "non_zar_rejected": col.non_zar_rejected,
            "agent_counts": dict(col.agent_counts),
            "titles_synthesized": col.titles_synthesized,
            "unknown_feature_tags": dict(col.unknown_feature_tags),
            "unmapped_property_types": dict(col.unmapped_property_types),
            "raw_data_keys": dict(col.raw_data_keys),
        }

        if dry_run:
            return WebboxRunResult(
                counts=RunCounts(seen=len(col.records)),
                agencies_upserted=0,
                agents_upserted=0,
                media_rows=0,
                withdrawn=0,
                reconciled=False,
                dry_run=True,
                **base,
            )

        agencies_created, agents_created = _apply_refs(
            feed_source_code, connect, col.agencies, col.agents
        )

        counts = import_listings(
            col.records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"webbox:{feed_source_code}",
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

        return WebboxRunResult(
            counts=counts,
            agencies_upserted=agencies_created,
            agents_upserted=agents_created,
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


def format_result(result: WebboxRunResult) -> str:
    c = result.counts
    lines = [
        f"mode                 {'dry-run' if result.dry_run else 'sync'}",
        f"source               {result.source}",
        f"outer XML form       {result.outer_form}  ({result.agencies_seen} <agency> seen)",
        f"properties in feed   {result.properties_in_feed}",
        f"  seen               {c.seen}",
        f"  inserted           {c.inserted}",
        f"  updated            {c.updated}",
        f"  failed             {c.failed}",
        f"  non-ZAR rejected   {result.non_zar_rejected}",
        f"titles synthesized   {result.titles_synthesized}",
        f"agencies upserted    {result.agencies_upserted}",
        f"agents upserted      {result.agents_upserted}",
        f"listing_media rows   {result.media_rows}",
        f"withdrawn (reconcile){result.withdrawn}" + ("" if result.reconciled else "  (skipped)"),
    ]
    if result.listing_types:
        lines.append(
            "listing types: " + ", ".join(f"{k}={v}" for k, v in result.listing_types.items())
        )
    if result.countries:
        lines.append("countries: " + ", ".join(f"{k}={v}" for k, v in result.countries.items()))
    if result.agent_counts:
        lines.append(
            "agent-count histogram: "
            + ", ".join(f"{k}={v}" for k, v in sorted(result.agent_counts.items()))
        )
    if result.unmapped_property_types:
        lines.append(
            "unmapped property types (quarantined): "
            + ", ".join(f"{k!r}={v}" for k, v in result.unmapped_property_types.items())
        )
    if result.unknown_feature_tags:
        lines.append(
            "unknown <features> tags: "
            + ", ".join(f"{k}={v}" for k, v in result.unknown_feature_tags.items())
        )
    if result.raw_data_keys:
        lines.append("raw_data keys captured (unlisted feed fields):")
        for key, n in sorted(result.raw_data_keys.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {key}  {n}")
    return "\n".join(lines)
