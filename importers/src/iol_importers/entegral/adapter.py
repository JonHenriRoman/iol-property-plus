"""Entegral adapter run — offices, then each office's listings, then media, then
per-office reconciliation.

For every office in ``officeslist`` (or the subset named on the command line):

1. ``officelistings`` for the office -> map -> one ``import_listings`` call.
2. Download every listing's photos, re-host them on our own storage, sync
   ``listing_media``, and point ``primary_image_url`` at the first re-hosted asset.
3. Reconcile — withdraw the office's listings absent from this response —
   **unless** the response was empty or the import had a failure (a transient
   empty response must never withdraw an office's whole book).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

import httpx
import psycopg
from psycopg.rows import dict_row

from iol_importers.config import MEDIA_DIR, resolve_database_url
from iol_importers.feeds.run import RunCounts
from iol_importers.lifecycle.withdraw import withdraw_missing
from iol_importers.listings.importer import import_listings
from iol_importers.media.db import sync_listing_media
from iol_importers.media.fetch import SourceUrlIndex, fetch_and_store
from iol_importers.media.store import MediaStore

from .client import EntegralAPIError, EntegralClient, office_name, office_reference
from .map import to_import_record

logger = logging.getLogger("iol_importers.entegral")

_FEED = "entegral"
_RAW_SCOPE_KEY = "entegral_office_reference"


@dataclass(frozen=True, slots=True)
class OfficeOutcome:
    office_reference: str
    office_name: str | None
    listings_seen: int
    counts: RunCounts
    photos_downloaded: int = 0
    photos_reused: int = 0
    photos_failed: int = 0
    media_rows_inserted: int = 0
    media_rows_pruned: int = 0
    withdrawn: int = 0
    reconciled: bool = False
    failed: bool = False


@dataclass(frozen=True, slots=True)
class EntegralRunResult:
    counts: RunCounts
    mode: str
    offices_seen: int
    offices_failed: int
    listings_seen: int
    photos_downloaded: int
    photos_reused: int
    photos_failed: int
    media_rows_inserted: int
    media_rows_pruned: int
    withdrawn: int
    checkpoint_written: bool
    offices: tuple[OfficeOutcome, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class _MediaDeps:
    store: MediaStore
    http: httpx.Client
    index: SourceUrlIndex
    refresh: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class _Config:
    feed_source_code: str
    max_listings_per_office: int | None
    reconcile: bool
    dry_run: bool
    connect: Callable[[], psycopg.Connection] | None
    tracking_connect: Callable[[], psycopg.Connection] | None
    media: _MediaDeps


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


def run(
    *,
    feed_source_code: str = _FEED,
    office_refs: Sequence[str] | None = None,
    max_offices: int | None = None,
    max_listings_per_office: int | None = None,
    with_media: bool = True,
    refresh_media: bool = False,
    reconcile: bool = True,
    dry_run: bool = False,
    connect: Callable[[], psycopg.Connection] | None = None,
    tracking_connect: Callable[[], psycopg.Connection] | None = None,
    write_checkpoint: bool = True,
    client: EntegralClient | None = None,
    store: MediaStore | None = None,
    media_index: SourceUrlIndex | None = None,
    media_http: httpx.Client | None = None,
) -> EntegralRunResult:
    own_client = client is None
    client = client or EntegralClient()
    own_http = media_http is None
    media_http = media_http or httpx.Client(follow_redirects=True)
    cfg = _Config(
        feed_source_code=feed_source_code,
        max_listings_per_office=max_listings_per_office,
        reconcile=reconcile,
        dry_run=dry_run,
        connect=connect,
        tracking_connect=tracking_connect,
        media=_MediaDeps(
            store=store or MediaStore(MEDIA_DIR),
            http=media_http,
            index=media_index or SourceUrlIndex(MEDIA_DIR),
            refresh=refresh_media,
            enabled=with_media,
        ),
    )
    started = dt.datetime.now(dt.UTC)

    try:
        selected = _select_offices(client.list_offices(), office_refs, max_offices)
        outcomes = [_process_office(client, office, cfg) for office in selected]

        total = RunCounts()
        for outcome in outcomes:
            total = _add(total, outcome.counts)
        offices_failed = sum(1 for o in outcomes if o.failed)
        bounded = max_offices is not None or max_listings_per_office is not None

        checkpoint_written = False
        if write_checkpoint and not dry_run and not bounded and offices_failed == 0:
            client.save_last_sync(started.strftime("%Y-%m-%d %H:%M:%S"))
            checkpoint_written = True

        return EntegralRunResult(
            counts=total,
            mode="dry-run" if dry_run else "sync",
            offices_seen=len(selected),
            offices_failed=offices_failed,
            listings_seen=sum(o.listings_seen for o in outcomes),
            photos_downloaded=sum(o.photos_downloaded for o in outcomes),
            photos_reused=sum(o.photos_reused for o in outcomes),
            photos_failed=sum(o.photos_failed for o in outcomes),
            media_rows_inserted=sum(o.media_rows_inserted for o in outcomes),
            media_rows_pruned=sum(o.media_rows_pruned for o in outcomes),
            withdrawn=sum(o.withdrawn for o in outcomes),
            checkpoint_written=checkpoint_written,
            offices=tuple(outcomes),
        )
    finally:
        if own_client:
            client.close()
        if own_http:
            media_http.close()


def _select_offices(
    offices: list[dict],
    office_refs: Sequence[str] | None,
    max_offices: int | None,
) -> list[dict]:
    wanted = {str(r).strip() for r in office_refs} if office_refs else None
    selected: list[dict] = []
    for office in offices:
        ref = office_reference(office)
        if ref is None:
            logger.warning("entegral: officeslist entry with no officereference — skipped")
            continue
        if wanted is None or ref in wanted:
            selected.append(office)
    return selected if max_offices is None else selected[:max_offices]


def _process_office(client: EntegralClient, office: dict, cfg: _Config) -> OfficeOutcome:
    ref = office_reference(office) or ""
    name = office_name(office)
    try:
        listings = [
            listing
            for listing in client.office_listings(ref)
            if str(listing.get("action", "create")).lower() != "delete"
        ]
    except (EntegralAPIError, httpx.HTTPError):
        logger.exception("entegral: office %s failed", ref)
        return OfficeOutcome(ref, name, 0, RunCounts(), failed=True)

    if cfg.max_listings_per_office is not None:
        listings = listings[: cfg.max_listings_per_office]

    mapped = [to_import_record(listing, office=office) for listing in listings]
    records = [rec for rec, _ in mapped]
    photos_by_vid = {
        rec["vendor_listing_id"]: urls for rec, urls in mapped if rec.get("vendor_listing_id")
    }
    base = OfficeOutcome(ref, name, len(listings), RunCounts(seen=len(records)))

    if cfg.dry_run:
        return base

    counts = import_listings(
        records,
        feed_source_code=cfg.feed_source_code,
        connect=cfg.connect,
        tracking_connect=cfg.tracking_connect,
        file_reference=f"entegral:officelistings:{ref}",
    )
    outcome = replace(base, counts=counts)

    if cfg.media.enabled and photos_by_vid:
        outcome = _attach_media(cfg, photos_by_vid, outcome)

    seen_vids = [r["vendor_listing_id"] for r in records if r.get("vendor_listing_id")]
    if cfg.reconcile and seen_vids and counts.failed == 0:
        result = withdraw_missing(
            cfg.feed_source_code,
            seen_vids,
            raw_scope=(_RAW_SCOPE_KEY, ref),
            connect=cfg.connect,
        )
        outcome = replace(outcome, withdrawn=result.withdrawn, reconciled=True)

    return outcome


_SELECT_IDS = """
    SELECT l.id AS id, l.vendor_listing_id AS vid
    FROM listings AS l
    JOIN feed_sources AS f ON f.id = l.feed_source_id
    WHERE f.code = %s AND l.vendor_listing_id = ANY(%s)
"""


def _attach_media(
    cfg: _Config,
    photos_by_vid: dict[str, list[str]],
    outcome: OfficeOutcome,
) -> OfficeOutcome:
    media = cfg.media
    downloaded = reused = failed = rows_inserted = rows_pruned = 0
    conn = (cfg.connect or _default_connect)()
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT_IDS, (cfg.feed_source_code, list(photos_by_vid)))
            rows = cur.fetchall()
        # Close the read's implicit transaction so each write below is top-level
        # and commits on its own (rather than nesting in a savepoint that the
        # final conn.close() would roll back).
        conn.rollback()

        for row in rows:
            urls = photos_by_vid.get(row["vid"]) or []
            if not urls:
                continue
            assets, stats = fetch_and_store(
                urls,
                feed="entegral",
                store=media.store,
                http=media.http,
                index=media.index,
                refresh=media.refresh,
            )
            downloaded += stats.downloaded
            reused += stats.reused
            failed += stats.failed
            if not assets:
                continue
            with conn.transaction():
                mc = conn.cursor(row_factory=dict_row)
                sync = sync_listing_media(mc, row["id"], assets)
                rows_inserted += sync.inserted
                rows_pruned += sync.pruned
                mc.execute(
                    "UPDATE listings SET primary_image_url = %s WHERE id = %s",
                    (assets[0].url, row["id"]),
                )
    finally:
        conn.close()

    return replace(
        outcome,
        photos_downloaded=downloaded,
        photos_reused=reused,
        photos_failed=failed,
        media_rows_inserted=rows_inserted,
        media_rows_pruned=rows_pruned,
    )


def format_result(result: EntegralRunResult) -> str:
    c = result.counts
    lines = [
        f"mode                {result.mode}",
        f"offices seen        {result.offices_seen}",
        f"offices failed      {result.offices_failed}",
        f"listings seen       {result.listings_seen}",
        f"  inserted          {c.inserted}",
        f"  updated           {c.updated}",
        f"  failed            {c.failed}",
        f"photos downloaded   {result.photos_downloaded}",
        f"photos reused       {result.photos_reused}",
        f"photos failed       {result.photos_failed}",
        f"listing_media rows  +{result.media_rows_inserted} / -{result.media_rows_pruned}",
        f"withdrawn (reconcile) {result.withdrawn}"
        + ("  (checkpoint written)" if result.checkpoint_written else ""),
    ]
    for outcome in result.offices:
        label = outcome.office_name or outcome.office_reference
        note = (
            "failed"
            if outcome.failed
            else (
                f"{outcome.counts.inserted} in / {outcome.counts.updated} upd / "
                f"{outcome.counts.failed} fail, {outcome.withdrawn} withdrawn"
            )
        )
        lines.append(f"  · {label}: {outcome.listings_seen} listings, {note}")
    return "\n".join(lines)
