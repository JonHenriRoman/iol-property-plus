"""RT3 (Rawson) adapter run — fetch every configured province file, parse with the
shared bracket-KV parser, map, import in one job, hotlink media, reconcile **per
province**.

RT3 splits one agency's book across one plain-text file per province
(``{base_url}/iol-{Province}.txt``, no auth). Every configured province file is
fetched up front; if any fetch fails the whole run aborts before anything is
imported or reconciled — a province that came back broken must never cause its
listings to be withdrawn.

Each province is a full resend with no delete signal, so a listing that stops
appearing is caught by
:func:`iol_importers.lifecycle.withdraw.withdraw_missing`, scoped to that
province via ``raw_data ->> 'rt3_province'`` (which refuses an empty seen set) and,
failing that, the ``iol-expire-listings`` sweep.

Agency / agent rows are created through the Step 14 resolvers. RT3 is a single
brand ("Rawson Properties") with per-listing ``Branch_ID`` / ``Branch_Name``
office identity, used directly as the agency. Photos are hotlinked, not re-hosted.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from iol_importers import bracket_kv
from iol_importers.config import resolve_database_url, resolve_rt3_base_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_missing
from iol_importers.listings.importer import import_listings

from .client import Rt3Client
from .map import to_import_record
from .source import resolve_source

logger = logging.getLogger("iol_importers.rt3")

_FEED = "rt3"


@dataclass(frozen=True, slots=True)
class Rt3RunResult:
    counts: RunCounts
    source: str  # "rt3:<feed_source_code>"
    provinces: dict[str, int]  # {province token: records parsed}
    records_in_feed: int
    branches: dict[str, str]  # {Branch_ID: Branch_Name}
    listing_types: dict[str, int]
    agent_counts: dict[str, int]  # {"0": n, "1": n, "2+": n}
    titles_synthesized: int
    records_without_gps: int
    unmapped_types: dict[str, int]
    media_rows: int
    withdrawn_by_province: dict[str, int]
    reconciled_provinces: list[str]
    raw_data_keys: dict[str, int]
    dry_run: bool


@dataclass
class _Collected:
    records: list[dict] = field(default_factory=list)
    photos_by_vid: dict[str, list[str]] = field(default_factory=dict)
    seen_by_province: dict[str, list[str]] = field(default_factory=dict)
    provinces: dict[str, int] = field(default_factory=dict)
    branches: dict[str, str] = field(default_factory=dict)
    listing_types: Counter = field(default_factory=Counter)
    agent_counts: Counter = field(default_factory=Counter)
    unmapped_types: Counter = field(default_factory=Counter)
    raw_data_keys: Counter = field(default_factory=Counter)
    titles_synthesized: int = 0
    without_gps: int = 0


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


def _agent_bucket(n: int) -> str:
    return "2+" if n >= 2 else str(n)


def _collect(bodies: dict[str, bytes], max_listings: int | None) -> _Collected:
    from .map import _PROPERTY_TYPE  # noqa: PLC0415 — internal, used only for the tally

    c = _Collected()
    for province, body in bodies.items():
        records = bracket_kv.parse(body)
        if max_listings is not None:
            records = records[:max_listings]
        c.provinces[province] = len(records)
        seen: list[str] = []
        for rec in records:
            mapped, images = to_import_record(rec, province=province)
            c.records.append(mapped)

            branch_id = (rec.get("Branch_ID") or "").strip()
            if branch_id:
                c.branches.setdefault(branch_id, (rec.get("Branch_Name") or "").strip())
            status = (rec.get("Status") or "").strip()
            if status:
                c.listing_types[status] += 1
            c.agent_counts[_agent_bucket(len(mapped.get("rt3_agents", []) or []))] += 1
            if mapped.get("latitude") is None:
                c.without_gps += 1
            if not (rec.get("Heading") or "").strip() and mapped.get("title"):
                c.titles_synthesized += 1

            type_raw = (rec.get("Type") or "").strip()
            resolved = _PROPERTY_TYPE.get(type_raw.lower(), type_raw)
            if type_raw and (resolved or "").lower() not in _KNOWN_TYPES_LOWER:
                c.unmapped_types[type_raw] += 1

            for key in mapped:
                if key.startswith("rt3_"):
                    c.raw_data_keys[key] += 1

            vid = mapped.get("vendor_listing_id")
            if vid and not mapped.get("__validation_error__"):
                seen.append(vid)
            if vid and images and not mapped.get("__validation_error__"):
                c.photos_by_vid[vid] = images
        c.seen_by_province[province] = seen
    return c


def _default_connect() -> psycopg.Connection:
    return psycopg.connect(resolve_database_url(), row_factory=dict_row)


_SELECT_LISTING_IDS = """
    SELECT l.id AS id, l.vendor_listing_id AS vid
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
"""


def _load_bodies(
    client: Rt3Client,
    base_url: str,
    provinces: tuple[str, ...],
    files: dict[str, str] | None,
) -> dict[str, bytes]:
    """Fetch (or read) every province up front. Any failure raises here, before
    the caller imports or reconciles anything."""
    bodies: dict[str, bytes] = {}
    for province in provinces:
        if files and province in files:
            bodies[province] = client.read_file(files[province])
        else:
            bodies[province] = client.fetch(f"{base_url}/iol-{province}.txt")
    return bodies


def run(
    *,
    feed_source_code: str = _FEED,
    provinces: tuple[str, ...] | list[str] | None = None,
    files: dict[str, str] | None = None,
    base_url: str | None = None,
    max_listings: int | None = None,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    client: Rt3Client | None = None,
) -> Rt3RunResult:
    if provinces is None and files is None:
        src = resolve_source(feed_source_code, connect=connect)
        provinces, base_url = src.provinces, base_url or src.base_url
    resolved_provinces = tuple(provinces or (files or {}).keys())
    resolved_base = (base_url or resolve_rt3_base_url()).rstrip("/")

    own_client = client is None
    client = client or Rt3Client()
    try:
        bodies = _load_bodies(client, resolved_base, resolved_provinces, files)

        col = _collect(bodies, max_listings)
        base = {
            "source": f"rt3:{feed_source_code}",
            "provinces": dict(col.provinces),
            "records_in_feed": len(col.records),
            "branches": dict(col.branches),
            "listing_types": dict(col.listing_types),
            "agent_counts": dict(col.agent_counts),
            "titles_synthesized": col.titles_synthesized,
            "records_without_gps": col.without_gps,
            "unmapped_types": dict(col.unmapped_types),
            "raw_data_keys": dict(col.raw_data_keys),
        }

        if dry_run:
            return Rt3RunResult(
                counts=RunCounts(seen=len(col.records)),
                media_rows=0,
                withdrawn_by_province={},
                reconciled_provinces=[],
                dry_run=True,
                **base,
            )

        counts = import_listings(
            col.records,
            feed_source_code=feed_source_code,
            connect=connect,
            tracking_connect=tracking_connect,
            file_reference=f"rt3:{feed_source_code}:{'+'.join(resolved_provinces)}",
        )
        media_rows = _sync_media(feed_source_code, col.photos_by_vid, connect)

        withdrawn_by_province: dict[str, int] = {}
        reconciled: list[str] = []
        if reconcile:
            for province, seen in col.seen_by_province.items():
                if not seen:
                    continue
                result = withdraw_missing(
                    feed_source_code,
                    seen,
                    raw_scope=("rt3_province", province),
                    connect=connect,
                )
                withdrawn_by_province[province] = result.withdrawn
                reconciled.append(province)

        return Rt3RunResult(
            counts=counts,
            media_rows=media_rows,
            withdrawn_by_province=withdrawn_by_province,
            reconciled_provinces=reconciled,
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


def format_result(result: Rt3RunResult) -> str:
    c = result.counts
    lines = [
        f"mode                 {'dry-run' if result.dry_run else 'sync'}",
        f"source               {result.source}",
        f"records in feed      {result.records_in_feed}",
        f"  seen               {c.seen}",
        f"  inserted           {c.inserted}",
        f"  updated            {c.updated}",
        f"  failed             {c.failed}",
        f"titles synthesized   {result.titles_synthesized}",
        f"records without GPS  {result.records_without_gps}",
        f"listing_media rows   {result.media_rows}",
    ]
    lines.append("provinces (records parsed):")
    for province, n in sorted(result.provinces.items()):
        withdrawn = result.withdrawn_by_province.get(province)
        recon = (
            f"  reconciled, {withdrawn} withdrawn"
            if province in result.reconciled_provinces
            else ""
        )
        lines.append(f"    {province}  {n}{recon}")
    if result.agent_counts:
        hist = ", ".join(f"{k} agent(s)={v}" for k, v in sorted(result.agent_counts.items()))
        lines.append(f"agent-count histogram: {hist}")
    if result.listing_types:
        types = ", ".join(f"{k}={v}" for k, v in result.listing_types.items())
        lines.append(f"listing types: {types}")
    if result.unmapped_types:
        um = ", ".join(f"{k!r}={v}" for k, v in result.unmapped_types.items())
        lines.append(f"unmapped Type values (quarantined): {um}")
    lines.append(f"branches: {len(result.branches)}")
    if result.raw_data_keys:
        lines.append("raw_data keys captured (unlisted feed fields):")
        for key, n in sorted(result.raw_data_keys.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {key}  {n}")
    return "\n".join(lines)
