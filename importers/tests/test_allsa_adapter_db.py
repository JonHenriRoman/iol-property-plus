"""Opt-in DB test — the AllSA fixture feed round-trips through Step 14.

Scratch schema (dropped CASCADE); the client reads a local fixture file, no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest -k allsa
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.allsa.adapter import run
from iol_importers.allsa.source import AllsaConfigError, resolve_source

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/allsa/fixtures/feed.xml"
_OPEN = "<Property>"


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
        agency_id="90000",
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        **kw,
    )


def _feed_without(reference: str, tmp_path: Path) -> str:
    head, _, rest = FIXTURE.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"<Reference>{reference}</Reference>" not in b]
    out = tmp_path / "trimmed.xml"
    out.write_text(head + "".join(kept))
    return str(out)


def _scalar(db, sql, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()["v"]


def test_first_run_imports_and_reports_branches(db):
    result = _run(db, file=str(FIXTURE))
    # 9 properties: 8 import, 1 (blank Heading) quarantined
    assert result.counts.inserted == 8
    assert result.counts.failed == 1
    assert result.properties_in_feed == 9
    assert set(result.branches) == {"90000", "90250", "90244", "90245"}
    assert result.branches["90000"] == 6

    assert _scalar(db, "SELECT count(*) AS v FROM agencies") == 4
    assert (
        _scalar(
            db, "SELECT count(*) AS v FROM agency_vendor_ids WHERE feed_source_id = %s", _fsid(db)
        )
        == 4
    )
    # agents keyed on lowercased email: alex (2103051 sends 'Alex@...'), bo, cory, dana, eli
    assert _scalar(db, "SELECT count(*) AS v FROM agents") == 5


def test_agency_website_is_enriched(db):
    _run(db, file=str(FIXTURE))
    site = _scalar(
        db,
        """
        SELECT a.website AS v FROM agencies a
        JOIN agency_vendor_ids m ON m.agency_id = a.id
        WHERE m.vendor_agency_id = '90250'
        """,
    )
    assert site == "https://example.test/kimberley"


def test_farm_and_apartment_both_import(db):
    _run(db, file=str(FIXTURE))
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r
            for r in conn.execute(
                "SELECT vendor_listing_id, erf_size_sqm, floor_size_sqm, bedrooms "
                "FROM listings WHERE vendor_listing_id IN ('4002', '3001')"
            ).fetchall()
        }
    assert rows["4002"]["erf_size_sqm"] == 42800  # Land_Size 4.28 ha
    assert rows["3001"]["floor_size_sqm"] == 48
    assert rows["3001"]["bedrooms"] == 2


def test_rerun_creates_zero_duplicates(db):
    first = _run(db, file=str(FIXTURE))
    n1 = _scalar(db, "SELECT count(*) AS v FROM listings")
    second = _run(db, file=str(FIXTURE))
    n2 = _scalar(db, "SELECT count(*) AS v FROM listings")
    assert n1 == n2 == first.counts.inserted
    assert second.counts.inserted == 0
    assert second.counts.updated == 8


def test_listing_absent_from_next_pull_is_withdrawn(db, tmp_path):
    _run(db, file=str(FIXTURE))
    trimmed = _feed_without("3001", tmp_path)
    result = _run(db, file=trimmed)
    assert result.withdrawn == 1
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute(
                "SELECT vendor_listing_id, status FROM listings "
                "WHERE vendor_listing_id IN ('3001', '2103051')"
            ).fetchall()
        }
    assert rows["3001"] == "Withdrawn"
    assert rows["2103051"] == "Active"
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 8  # nothing deleted


def test_empty_feed_withdraws_nothing(db):
    _run(db, file=str(FIXTURE))
    empty = FIXTURE.parent / "empty.xml"
    result = _run(db, file=str(empty))
    assert result.withdrawn == 0
    assert result.reconciled is False
    assert _scalar(db, "SELECT count(*) AS v FROM listings WHERE status = 'Active'") == 8


def test_dry_run_writes_nothing(db):
    result = _run(db, file=str(FIXTURE), dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 9
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 0
    assert _scalar(db, "SELECT count(*) AS v FROM agencies") == 0


def test_media_rows_hotlinked(db):
    result = _run(db, file=str(FIXTURE))
    assert result.media_rows > 0
    urls = _scalar(
        db,
        "SELECT count(*) AS v FROM listing_media WHERE url LIKE %s",
        "https://img.example.test/%",
    )
    assert urls == result.media_rows


def test_resolve_source_reads_auth_config(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url, auth_config) "
            "VALUES ('allsa-77', 'AllSA 77', 'https://x.test/iol.ashx', '{\"agency_id\": \"77\"}')"
        )
        conn.commit()
    src = resolve_source("allsa-77", connect=db.data_connect)
    assert src.agency_id == "77"
    assert src.base_url == "https://x.test/iol.ashx"


def test_resolve_source_without_agency_id_raises(db):
    with pytest.raises(AllsaConfigError):
        resolve_source(FEED, connect=db.data_connect)  # demo-feed has no agency_id


def _fsid(db):
    return _scalar(db, "SELECT id AS v FROM feed_sources WHERE code = %s", FEED)
