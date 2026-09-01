"""Opt-in DB test — the RT3 two-province fixtures + real extract through Step 14.

Scratch schema (dropped CASCADE); the client reads local fixture files, no network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest -k rt3
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.rt3.adapter import run
from iol_importers.rt3.client import Rt3APIError, Rt3Client
from iol_importers.rt3.source import Rt3ConfigError, resolve_source
from rt3_mock import BASE_URL, mock_transport, set_province_error

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"
FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/rt3/fixtures"
GAUTENG = FIXTURES / "iol-Gauteng.txt"
WESTERN_CAPE = FIXTURES / "iol-Western_Cape.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "rt3.txt"
_OPEN = "[[Listing_Start]]"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _both() -> dict[str, str]:
    return {"Gauteng": str(GAUTENG), "Western_Cape": str(WESTERN_CAPE)}


def _run(db, files=None, **kw):
    return run(
        feed_source_code=FEED,
        files=files or _both(),
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        **kw,
    )


def _gauteng_without(reference: str, tmp_path: Path) -> str:
    head, _, rest = GAUTENG.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"[[Reference:{reference}/]]" not in b]
    out = tmp_path / "iol-Gauteng.txt"
    out.write_text(head + "".join(kept))
    return str(out)


def _scalar(db, sql, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()["v"]


def test_two_provinces_import_end_to_end_in_one_run(db):
    result = _run(db)
    assert result.provinces == {"Gauteng": 5, "Western_Cape": 3}
    assert result.records_in_feed == 8
    # 1400003 "Guest House" is the only failure (mapping/quarantine)
    assert result.counts.inserted == 7
    assert result.counts.failed == 1
    assert _scalar(db, "SELECT error_type AS v FROM import_errors") == "mapping"
    assert result.agent_counts == {"0": 2, "1": 4, "2+": 2}
    assert result.unmapped_types == {"Guest House": 1}

    with db.connect() as conn:
        types = {
            r["vendor_listing_id"]: r["name"]
            for r in conn.execute(
                "SELECT l.vendor_listing_id, p.name FROM listings l "
                "JOIN property_types p ON p.id = l.property_type_id"
            ).fetchall()
        }
    assert types["1289051"] == "Commercial"
    assert types["1400001"] == "House"
    assert types["1400002"] == "Office"  # Commercial - Offices
    assert types["1500001"] == "Townhouse"  # Townhouse - sectional

    # co-agent roster preserved in raw_data
    assert (
        _scalar(
            db,
            "SELECT jsonb_array_length(raw_data->'rt3_agents') AS v FROM listings "
            "WHERE vendor_listing_id = '1400001'",
        )
        == 3
    )
    assert (
        _scalar(
            db,
            "SELECT raw_data->'rt3_agents'->0->>'name' AS v FROM listings "
            "WHERE vendor_listing_id = '1400001'",
        )
        == "Thandi Nkosi"
    )
    # kitchen fittings parsed into a list
    assert (
        _scalar(
            db,
            "SELECT raw_data->'rt3_kitchen_fittings'->>0 AS v FROM listings "
            "WHERE vendor_listing_id = '1312993'",
        )
        == "extractor fan"
    )
    # hotlinked media
    assert result.media_rows == _scalar(
        db, "SELECT count(*) AS v FROM listing_media WHERE media_type = 'Photo'"
    )
    assert result.media_rows >= 8


def test_gps_split_persisted(db):
    _run(db)
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: (r["latitude"], r["longitude"])
            for r in conn.execute(
                "SELECT vendor_listing_id, latitude, longitude FROM listings"
            ).fetchall()
        }
    assert rows["1289051"][0] is not None
    assert rows["1400002"] == (None, None)  # "0.00000000,0.00000000" sentinel


def test_rerun_creates_zero_duplicates(db):
    first = _run(db)
    n1 = _scalar(db, "SELECT count(*) AS v FROM listings")
    second = _run(db)
    n2 = _scalar(db, "SELECT count(*) AS v FROM listings")
    assert n1 == n2 == first.counts.inserted == 7
    assert second.counts.inserted == 0
    assert second.counts.updated == 7


def test_per_province_reconcile_isolates_provinces(db, tmp_path):
    _run(db)
    result = _run(
        db,
        files={
            "Gauteng": _gauteng_without("1289051", tmp_path),
            "Western_Cape": str(WESTERN_CAPE),
        },
    )
    assert result.withdrawn_by_province.get("Gauteng") == 1
    assert result.withdrawn_by_province.get("Western_Cape", 0) == 0
    with db.connect() as conn:
        status = {
            r["vendor_listing_id"]: r["status"]
            for r in conn.execute("SELECT vendor_listing_id, status FROM listings").fetchall()
        }
    assert status["1289051"] == "Withdrawn"
    assert status["1312993"] == "Active"  # other Gauteng listing untouched
    assert status["1500001"] == "Active"  # every Western_Cape listing untouched
    assert status["1500002"] == "Active"
    assert status["1500003"] == "Active"
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 7  # nothing deleted


def test_one_province_failing_aborts_and_withdraws_nothing(db):
    _run(db)
    client = Rt3Client(transport=mock_transport(), retry_base_delay=0.0)
    set_province_error("Western_Cape", 500)
    with pytest.raises(Rt3APIError):
        run(
            feed_source_code=FEED,
            provinces=("Gauteng", "Western_Cape"),
            base_url=BASE_URL,
            client=client,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
        )
    assert _scalar(db, "SELECT count(*) AS v FROM listings WHERE status = 'Active'") == 7


def test_dry_run_writes_nothing(db):
    result = _run(db, dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 8
    assert _scalar(db, "SELECT count(*) AS v FROM listings") == 0
    assert _scalar(db, "SELECT count(*) AS v FROM agents") == 0


def test_resolve_source_reads_the_province_list(db):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO feed_sources (code, name, base_url, auth_config) "
            "VALUES ('rt3-x', 'RT3 X', 'https://x.test', "
            '\'{"provinces": ["Gauteng", "Western_Cape"]}\')'
        )
        conn.commit()
    src = resolve_source("rt3-x", connect=db.data_connect)
    assert src.provinces == ("Gauteng", "Western_Cape")
    assert src.base_url == "https://x.test"


def test_resolve_source_without_provinces_raises(db):
    with pytest.raises(Rt3ConfigError):
        resolve_source(FEED, connect=db.data_connect)  # demo-feed has no provinces


def test_real_two_record_extract_imports_clean(db):
    result = run(
        feed_source_code=FEED,
        files={"Gauteng": str(REAL)},
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )
    assert result.provinces == {"Gauteng": 2}
    assert result.counts.inserted == 2
    assert result.counts.failed == 0
    assert result.agent_counts == {"0": 1, "1": 1}
    with db.connect() as conn:
        rows = {
            r["vendor_listing_id"]: (r["latitude"], r["listing_type"])
            for r in conn.execute(
                "SELECT vendor_listing_id, latitude, listing_type FROM listings"
            ).fetchall()
        }
    assert rows["1289051"][1] == "Rental"
    assert rows["1289051"][0] is not None
    assert rows["1312993"][1] == "Sale"
