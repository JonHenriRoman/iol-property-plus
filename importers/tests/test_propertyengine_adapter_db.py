"""Opt-in DB test — the PropertyEngine fixture feed round-trips through Step 14.

Scratch schema (dropped CASCADE); the client is fixture-backed, so no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.config import PropertyengineFeed
from iol_importers.propertyengine.adapter import run
from iol_importers.propertyengine.client import PropertyEngineClient
from propertyengine_mock import FEED_URL, mock_transport, set_body

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/propertyengine/fixtures"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


@pytest.fixture
def rig(db):
    feed = PropertyengineFeed(FEED_URL, auth_token=None, auth_scheme="bearer")
    transport = mock_transport()  # resets mock state once, up front

    def _run(**kw):
        return run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=PropertyEngineClient(feed=feed, transport=transport, retry_base_delay=0.0),
            **kw,
        )

    return db, _run


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def test_one_listing_per_status_round_trips(rig):
    db, _run = rig
    result = _run()
    # 5 records: 4 import, 1 (bad Type) is quarantined
    assert result.counts.failed == 1
    assert result.counts.inserted == 4
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["listing_type"]
            for r in conn.execute(
                "SELECT vendor_listing_id, listing_type FROM listings"
            ).fetchall()
        }
    assert rows["900001"] == "Sale"
    assert rows["900003"] == "Rental"
    assert rows["900004"] == "Rental"  # Holiday -> Rental


def test_location_and_free_text_resolve_to_the_same_suburb(rig):
    db, _run = rig
    _run()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT vendor_listing_id, suburb_id FROM listings "
            "WHERE vendor_listing_id IN ('900001', '900002')"
        ).fetchall()
    suburb_ids = {r["suburb_id"] for r in rows}
    assert len(rows) == 2
    assert len(suburb_ids) == 1
    assert None not in suburb_ids


def test_bad_type_lands_in_import_errors_not_a_crash(rig):
    db, _run = rig
    result = _run()
    with db.connect() as conn:
        err = conn.execute(
            "SELECT error_type FROM import_errors WHERE vendor_listing_id = '900005'"
        ).fetchone()
        job = conn.execute(
            "SELECT status FROM import_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        exists = conn.execute(
            "SELECT 1 FROM listings WHERE vendor_listing_id = '900005'"
        ).fetchone()
    assert err["error_type"] == "validation"
    assert job["status"] == "PartialSuccess"
    assert exists is None
    assert result.counts.inserted == 4


def test_price_zero_is_contact_for_price(rig):
    db, _run = rig
    _run()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT price, price_on_application FROM listings WHERE vendor_listing_id = '900004'"
        ).fetchone()
    assert row["price"] is None
    assert row["price_on_application"] is True


def test_reprocessing_produces_zero_duplicates(rig):
    db, _run = rig
    _run()
    listings = _count(db, "SELECT count(*) FROM listings")
    media = _count(db, "SELECT count(*) FROM listing_media")
    second = _run()
    assert second.counts.inserted == 0
    assert second.counts.updated == 4
    assert _count(db, "SELECT count(*) FROM listings") == listings
    assert _count(db, "SELECT count(*) FROM listing_media") == media
    assert _count(db, "SELECT count(*) FROM import_jobs") == 2


def test_photos_are_hotlinked_in_listing_media(rig):
    db, _run = rig
    _run()
    with db.connect() as conn:
        urls = [r["url"] for r in conn.execute("SELECT url FROM listing_media").fetchall()]
    assert urls
    assert all(u.startswith("https://images.example.test/") for u in urls)


def test_listing_absent_from_a_later_pull_is_withdrawn(rig):
    db, _run = rig
    _run()
    assert _count(db, "SELECT count(*) FROM listings WHERE status = 'Active'") == 4

    # a later feed file that no longer carries 900003
    full = (FIXTURES / "feed.xml").read_text()
    trimmed = _drop_property(full, "900003")
    set_body(trimmed.encode(), content_type="application/xml")
    result = _run()

    assert result.reconciled is True
    assert result.withdrawn == 1
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute("SELECT vendor_listing_id, status FROM listings").fetchall()
        }
    assert rows["900003"] == "Withdrawn"
    assert rows["900001"] == "Active"


def _drop_property(xml: str, unique_id: str) -> str:
    blocks = xml.split("  <Property>")
    kept = [blocks[0]] + [
        b for b in blocks[1:] if f"<UniqueID>{unique_id}</UniqueID>" not in b
    ]
    return "  <Property>".join(kept)


def test_dry_run_writes_nothing(rig):
    db, _run = rig
    result = _run(dry_run=True)
    assert result.mode == "dry-run"
    assert result.counts.seen == 5
    assert _count(db, "SELECT count(*) FROM listings") == 0
