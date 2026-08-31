"""Opt-in DB test — Entegral fixtures round-trip through the Step 14 importer.

Scratch schema (dropped CASCADE); the Entegral client and the media HTTP client
are both fixture-backed, so this makes no network calls.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import httpx
import pytest

from entegral_mock import mock_transport, office_listings, set_office_listings
from iol_importers.config import EntegralCredentials
from iol_importers.entegral.adapter import run
from iol_importers.entegral.client import EntegralClient
from iol_importers.media.fetch import SourceUrlIndex
from iol_importers.media.store import MediaStore

pytestmark = pytest.mark.dbtest

CREDS = EntegralCredentials("sandbox-user", "secret", "https://sync.entegral.net/api")
FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


@pytest.fixture
def rig(db, tmp_path):
    transport = mock_transport()
    client = EntegralClient(credentials=CREDS, transport=transport, retry_base_delay=0.0)
    media_http = httpx.Client(transport=transport, follow_redirects=True)

    def _run(**kw):
        return run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=EntegralClient(credentials=CREDS, transport=transport, retry_base_delay=0.0),
            media_http=media_http,
            store=MediaStore(tmp_path / "media"),
            media_index=SourceUrlIndex(tmp_path / "media"),
            write_checkpoint=False,
            **kw,
        )

    yield db, _run, transport
    media_http.close()
    client.close()


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def test_listing_round_trips_with_agent_and_office_name(rig):
    db, _run, _ = rig
    result = _run()
    assert result.offices_failed == 0
    assert result.counts.failed == 0
    assert result.counts.inserted == result.listings_seen > 0

    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT ag.first_name || ' ' || ag.last_name AS agent,
                   agc.name AS agency
            FROM listings l
            JOIN agents ag ON ag.id = l.agent_id
            JOIN agencies agc ON agc.id = l.agency_id
            WHERE l.vendor_listing_id = 'L-1001'
            """
        ).fetchone()
    assert row["agent"].strip() == "Jordan Adams"
    assert row["agency"] == "Demo Property Group Claremont"


def test_photos_are_rehosted_not_proxied(rig):
    db, _run, _ = rig
    _run()
    with db.connect() as conn:
        urls = [r["url"] for r in conn.execute("SELECT url FROM listing_media").fetchall()]
        primary = conn.execute(
            "SELECT primary_image_url FROM listings WHERE vendor_listing_id = 'L-1001'"
        ).fetchone()["primary_image_url"]
    assert urls, "expected listing_media rows"
    # every media URL is a site-relative path on our own origin — no vendor host,
    # no scheme, content-addressed under the feed's own folder
    assert all(u.startswith("/media/entegral/") for u in urls)
    assert not any("://" in u or "img.entegral.net" in u for u in urls)
    assert primary.startswith("/media/entegral/")


def test_reimport_same_office_zero_duplicates(rig):
    db, _run, _ = rig
    _run()
    listings = _count(db, "SELECT count(*) FROM listings")
    media = _count(db, "SELECT count(*) FROM listing_media")
    second = _run()
    assert second.counts.inserted == 0
    assert _count(db, "SELECT count(*) FROM listings") == listings
    assert _count(db, "SELECT count(*) FROM listing_media") == media


def test_dropped_listing_is_withdrawn_siblings_untouched(rig):
    db, _run, transport = rig
    _run()
    assert _count(db, "SELECT count(*) FROM listings") == 4
    # OFF001's second response no longer carries L-1002
    keep = [x for x in office_listings("OFF001") if x["clientPropertyID"] != "L-1002"]
    set_office_listings("OFF001", keep)
    result = _run()
    assert result.withdrawn == 1
    assert _count(db, "SELECT count(*) FROM listings") == 4  # soft, not hard
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute("SELECT vendor_listing_id, status FROM listings").fetchall()
        }
    assert rows["L-1002"] == "Withdrawn"
    assert rows["L-1001"] == "Active"
    assert rows["L-2001"] == "Active"


def test_empty_office_response_withdraws_nothing(rig):
    db, _run, transport = rig
    _run()
    active_before = _count(db, "SELECT count(*) FROM listings WHERE status = 'Active'")
    set_office_listings("OFF001", [])
    result = _run()
    assert result.withdrawn == 0
    assert _count(db, "SELECT count(*) FROM listings WHERE status = 'Active'") == active_before


def test_missing_agent_name_is_recorded_not_imported(rig):
    db, _run, transport = rig
    bad = office_listings("OFF002")
    bad[0]["contact"][0]["fullName"] = ""
    set_office_listings("OFF002", bad)
    _run(office_refs=["OFF002"])
    with db.connect() as conn:
        err = conn.execute(
            "SELECT error_type, error_message FROM import_errors WHERE vendor_listing_id = 'L-2001'"
        ).fetchone()
        exists = conn.execute(
            "SELECT 1 FROM listings WHERE vendor_listing_id = 'L-2001'"
        ).fetchone()
    assert err["error_type"] == "validation"
    assert "agent" in err["error_message"]
    assert exists is None


def test_photo_download_failure_does_not_fail_listing(rig):
    db, _run, transport = rig
    broken = office_listings("OFF001")
    for photo in broken[0]["photos"]:
        photo["imgUrl"] = "https://img.entegral.net/p/OFF001/404/missing.jpg"
    set_office_listings("OFF001", broken)
    result = _run(office_refs=["OFF001"])
    assert result.counts.failed == 0
    assert result.photos_failed >= 1
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM listings WHERE vendor_listing_id = 'L-1001'"
        ).fetchone()
    assert row["status"] == "Active"


def test_dry_run_writes_nothing(rig):
    db, _run, _ = rig
    result = _run(dry_run=True)
    assert result.mode == "dry-run"
    assert result.counts.seen > 0
    assert _count(db, "SELECT count(*) FROM listings") == 0
