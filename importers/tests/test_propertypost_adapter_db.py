"""Opt-in DB test — the PropertyPost fixture + real extract round-trip through Step 14.

Scratch schema (dropped CASCADE); the client reads a local fixture file, no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest -k propertypost
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.propertypost.adapter import run
from iol_importers.propertypost.client import PropertypostAPIError, PropertypostClient
from iol_importers.propertypost.source import PropertypostConfigError, resolve_source
from propertypost_mock import FEED_URL, mock_transport, set_body

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/propertypost/fixtures/feed.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "propertypost.txt"
_OPEN = "[[Listing_Start]]"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _run(db, **kw):
    return run(
        feed_source_code=FEED,
        feed_url="http://feed.example.test/demo.txt",
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        **kw,
    )


def _feed_without(reference: str, tmp_path: Path) -> str:
    head, _, rest = FIXTURE.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"[[Reference:{reference}/]]" not in b]
    out = tmp_path / "trimmed.txt"
    out.write_text(head + "".join(kept))
    return str(out)


def _scalar(db, sql, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()["v"]


def test_real_two_record_extract_imports_clean(db):
    """The objective's headline validation — both real samples (a To Let commercial
    with no GPS and an empty Features_Description, and a For Sale house) end to end."""
    result = _run(db, file=str(REAL))
    assert result.records_in_feed == 2
    assert result.counts.inserted == 2
    assert result.counts.failed == 0

    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r
            for r in conn.execute(
                "SELECT vendor_listing_id, listing_type, latitude, longitude, features "
                "FROM listings"
            ).fetchall()
        }
    assert rows["5073542"]["listing_type"] == "Rental"
    assert (rows["5073542"]["latitude"], rows["5073542"]["longitude"]) == (None, None)
    assert "Fence" in rows["5073542"]["features"]
    assert rows["5084381"]["listing_type"] == "Sale"
    assert rows["5084381"]["latitude"] is not None
    # empty Features_Description never becomes a raw_data key
    assert (
        _scalar(
            db,
            "SELECT count(*) AS v FROM listings "
            "WHERE raw_data ? 'propertypost_Features_Description'",
        )
        == 0
    )


def test_fixture_imports_end_to_end_with_duplicate_reference_collapsed(db):
    result = _run(db, file=str(FIXTURE))
    assert result.records_in_feed == 8
    assert result.distinct_references == 7
    assert result.duplicate_references == 1
    assert result.branches == {"39350": "BST PROPERTIES (PTY) LTD"}
    assert result.listing_types == {"To Let": 2, "For Sale": 6}
    assert result.titles_synthesized == 2
    assert result.field_conflicts == {"bedrooms": 1}
    assert result.records_without_gps == 3

    assert result.counts.inserted == 7  # 8 records, the duplicate is a no-op
    assert result.counts.failed == 0
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 7

    with db.connect() as conn:
        types = {
            r["vendor_listing_id"]: r["name"]
            for r in conn.execute(
                "SELECT l.vendor_listing_id, p.name FROM listings l "
                "JOIN property_types p ON p.id = l.property_type_id"
            ).fetchall()
        }
    assert types["5090004"] == "Vacant Land"  # Stand
    assert types["5090005"] == "Farm"  # Smallholding

    # POA row
    assert (
        _scalar(
            db,
            "SELECT price_on_application AS v FROM listings WHERE vendor_listing_id = '5090003'",
        )
        is True
    )
    # the divergent Beds/Bedrooms pair is recorded, not silently dropped
    assert (
        _scalar(
            db,
            "SELECT raw_data->>'propertypost_bedrooms_conflict' AS v FROM listings "
            "WHERE vendor_listing_id = '5090004'",
        )
        == "Bedrooms=4.00 Beds=3.00"
    )
    assert (
        _scalar(
            db,
            "SELECT bedrooms AS v FROM listings WHERE vendor_listing_id = '5090004'",
        )
        == 4
    )
    # Admin_ID captured, distinct from the agent
    assert (
        _scalar(
            db,
            "SELECT raw_data->>'propertypost_admin_email' AS v FROM listings "
            "WHERE vendor_listing_id = '5084381'",
        )
        == "brendan@bstproperties.co.za"
    )
    # Carports -> parking_spaces
    assert (
        _scalar(
            db,
            "SELECT parking_spaces AS v FROM listings WHERE vendor_listing_id = '5090003'",
        )
        == 2
    )
    # Verified -> last_updated_by_vendor_at
    assert _scalar(
        db,
        "SELECT last_updated_by_vendor_at IS NOT NULL AS v FROM listings "
        "WHERE vendor_listing_id = '5084381'",
    )
    # hotlinked media
    assert result.media_rows == _scalar(
        db, "SELECT count(*) AS v FROM listing_media WHERE media_type = 'Photo'"
    )
    assert result.media_rows >= 7


def test_rerun_creates_zero_duplicates(db):
    first = _run(db, file=str(FIXTURE))
    n1 = _scalar(db, "SELECT count(*) AS v FROM listings")
    second = _run(db, file=str(FIXTURE))
    n2 = _scalar(db, "SELECT count(*) AS v FROM listings")
    assert n1 == n2 == first.counts.inserted == 7
    assert second.counts.inserted == 0
    assert second.counts.updated == 8  # 8 upserts (the duplicate Reference re-hits its row)


def test_listing_absent_from_next_pull_is_withdrawn(db, tmp_path):
    _run(db, file=str(FIXTURE))
    result = _run(db, file=_feed_without("5084381", tmp_path))
    assert result.withdrawn == 1
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute(
                "SELECT vendor_listing_id, status FROM listings "
                "WHERE vendor_listing_id IN ('5084381', '5073542')"
            ).fetchall()
        }
    assert rows["5084381"] == "Withdrawn"
    assert rows["5073542"] == "Active"
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 7  # nothing deleted


def test_broken_fetch_withdraws_nothing(db):
    _run(db, file=str(FIXTURE))
    client = PropertypostClient(transport=mock_transport(), retry_base_delay=0.0)
    set_body(b"<html>error</html>", content_type="text/html")
    with pytest.raises(PropertypostAPIError):
        run(
            feed_source_code=FEED,
            feed_url=FEED_URL,
            client=client,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
        )
    assert _scalar(db, "SELECT count(*) AS v FROM listings WHERE status = 'Active'") == 7


def test_dry_run_writes_nothing(db):
    result = _run(db, file=str(FIXTURE), dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 8
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 0
    assert _scalar(db, "SELECT count(*) AS v FROM agents") == 0


def test_resolve_source_reads_base_url(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url) "
            "VALUES ('propertypost-x', 'PropertyPost X', 'http://x.test/XAgency.txt')"
        )
        conn.commit()
    src = resolve_source("propertypost-x", connect=db.data_connect)
    assert src.feed_url == "http://x.test/XAgency.txt"


def test_resolve_source_without_a_file_path_raises(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url) "
            "VALUES ('propertypost-bare', 'PropertyPost Bare', 'http://lms.propertypost.co.za')"
        )
        conn.commit()
    with pytest.raises(PropertypostConfigError):
        resolve_source("propertypost-bare", connect=db.data_connect)
