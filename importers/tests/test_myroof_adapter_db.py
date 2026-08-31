"""Opt-in DB test — the MyRoof fixture + real extract round-trip through Step 14.

Scratch schema (dropped CASCADE); the client reads a local fixture file, no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest -k myroof
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.myroof.adapter import run
from iol_importers.myroof.client import MyroofClient
from iol_importers.myroof.source import MyroofConfigError, resolve_source
from myroof_mock import BASE_URL, mock_transport, set_body

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/myroof/fixtures/feed.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "myroof.txt"
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
        token="demo-token",
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


def test_fixture_imports_end_to_end(db):
    result = _run(db, file=str(FIXTURE))
    assert result.records_in_feed == 6
    # 6 records: 5 import, MR300002 (Type "Guest House") is the only failure
    assert result.counts.inserted == 5
    assert result.counts.failed == 1
    assert _scalar(db, "SELECT error_type AS v FROM import_errors") == "mapping"

    with db.connect() as conn:
        types = {
            r["vendor_listing_id"]: r["name"]
            for r in conn.execute(
                "SELECT l.vendor_listing_id, p.name FROM listings l "
                "JOIN property_types p ON p.id = l.property_type_id"
            ).fetchall()
        }
    assert types == {
        "MR149308": "House",
        "MR706715": "House",
        "MR300001": "Townhouse",
        "MR300003": "Apartment",
        "MR300004": "Vacant Land",
    }
    # price-on-application row
    assert (
        _scalar(
            db,
            "SELECT price_on_application AS v FROM listings WHERE vendor_listing_id = 'MR300001'",
        )
        is True
    )
    # agent rows labelled by program; email is the vendor id (Step 14's resolver
    # stores it on agent_vendor_ids and splits the name into first/last)
    assert (
        _scalar(
            db,
            "SELECT (a.first_name || ' ' || a.last_name) AS v FROM agents a "
            "JOIN agent_vendor_ids m ON m.agent_id = a.id "
            "WHERE m.vendor_agent_id = 'sbsa_repo@myroof.co.za'",
        )
        == "Standard Bank Repossessed"
    )
    # hotlinked media
    assert result.media_rows == _scalar(
        db, "SELECT count(*) AS v FROM listing_media WHERE media_type = 'Photo'"
    )
    assert result.media_rows >= 5
    # Video_URL captured in raw_data, not as media
    assert (
        _scalar(
            db,
            "SELECT raw_data->'myroof_Video_URL'->>0 AS v FROM listings "
            "WHERE vendor_listing_id = 'MR706715'",
        )
        == "https://www.youtube.com/watch?v=abc123"
    )


def test_gps_split_across_the_fixture(db):
    _run(db, file=str(FIXTURE))
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: (r["latitude"], r["longitude"])
            for r in conn.execute(
                "SELECT vendor_listing_id, latitude, longitude FROM listings"
            ).fetchall()
        }
    assert rows["MR149308"][0] is not None
    assert rows["MR706715"] == (None, None)  # "," sentinel
    assert rows["MR300004"] == (None, None)


def test_real_two_record_extract_imports_clean(db):
    real_result = run(
        feed_source_code=FEED,
        token="demo-token",
        file=str(REAL),
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )
    assert real_result.records_in_feed == 2
    assert real_result.counts.inserted == 2
    assert real_result.counts.failed == 0
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: (r["latitude"], r["longitude"])
            for r in conn.execute(
                "SELECT vendor_listing_id, latitude, longitude FROM listings"
            ).fetchall()
        }
    assert rows["MR149308"][0] is not None  # real record 1 has coords
    assert rows["MR706715"] == (None, None)  # real record 2 GPS is ","


def test_rerun_creates_zero_duplicates(db):
    first = _run(db, file=str(FIXTURE))
    n1 = _scalar(db, "SELECT count(*) AS v FROM listings")
    second = _run(db, file=str(FIXTURE))
    n2 = _scalar(db, "SELECT count(*) AS v FROM listings")
    assert n1 == n2 == first.counts.inserted
    assert second.counts.inserted == 0
    assert second.counts.updated == 5


def test_listing_absent_from_next_pull_is_withdrawn(db, tmp_path):
    _run(db, file=str(FIXTURE))
    result = _run(db, file=_feed_without("MR300001", tmp_path))
    assert result.withdrawn == 1
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute(
                "SELECT vendor_listing_id, status FROM listings "
                "WHERE vendor_listing_id IN ('MR300001', 'MR149308')"
            ).fetchall()
        }
    assert rows["MR300001"] == "Withdrawn"
    assert rows["MR149308"] == "Active"
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 5  # nothing deleted


def test_broken_fetch_withdraws_nothing(db):
    _run(db, file=str(FIXTURE))
    client = MyroofClient(base_url=BASE_URL, transport=mock_transport(), retry_base_delay=0.0)
    set_body(b"<html>error</html>", content_type="text/html")
    from iol_importers.myroof.client import MyroofAPIError

    with pytest.raises(MyroofAPIError):
        run(
            feed_source_code=FEED,
            token="demo-token",
            client=client,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
        )
    assert _scalar(db, "SELECT count(*) AS v FROM listings WHERE status = 'Active'") == 5


def test_dry_run_writes_nothing(db):
    result = _run(db, file=str(FIXTURE), dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 6
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 0
    assert _scalar(db, "SELECT count(*) AS v FROM agents") == 0


def test_resolve_source_reads_token(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url, auth_config) "
            "VALUES ('myroof-x', 'MyRoof X', 'https://x.test', '{\"token\": \"abc123\"}')"
        )
        conn.commit()
    src = resolve_source("myroof-x", connect=db.data_connect)
    assert src.token == "abc123"
    assert src.base_url == "https://x.test"


def test_resolve_source_without_token_raises(db):
    with pytest.raises(MyroofConfigError):
        resolve_source(FEED, connect=db.data_connect)  # demo-feed has no token
