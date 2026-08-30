"""Opt-in DB test — Propdata fixtures round-trip through the Step 14 importer.

Scratch schema (dropped CASCADE); the Propdata client is fixture-backed, so this
makes no network calls.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import json
import os

import pytest

from iol_importers.config import PropdataCredentials
from iol_importers.listings.importer import import_listings
from iol_importers.propdata.adapter import run
from iol_importers.propdata.client import PropdataClient
from iol_importers.propdata.map import to_import_record
from propdata_mock import FIXTURES, mock_transport

pytestmark = pytest.mark.dbtest

CREDS = PropdataCredentials("u", "p", "https://api-gw.propdata.net/users/public-api/login/")
FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _client(tmp_path) -> PropdataClient:
    c = PropdataClient(
        "harcourts.co.za", credentials=CREDS, transport=mock_transport(), token_dir=tmp_path
    )
    c.ensure_token()
    return c


def _run_all(db, client) -> dict:
    results = run(
        site_domain="harcourts.co.za",
        feed_source_code=FEED,
        categories=("residential", "commercial", "projects"),
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        page_limit=1,
        client=client,
    )
    holiday_raw = json.loads((FIXTURES / "holiday_page1.json").read_text())["results"]
    results["holiday"] = import_listings(
        [to_import_record(r, category="holiday", client=client) for r in holiday_raw],
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        file_reference="propdata:test:holiday",
    )
    return results


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def test_all_four_categories_round_trip(db, tmp_path):
    results = _run_all(db, _client(tmp_path))

    for category in ("residential", "commercial", "holiday", "projects"):
        assert results[category].failed == 0, f"{category} had failures"
        assert results[category].inserted > 0, f"{category} inserted nothing"

    assert _count(db, "SELECT count(*) FROM import_errors") == 0
    # every category tag is present on the imported rows
    with db.connect() as conn:
        tags = {
            r["raw_data"]["propdata_category"]
            for r in conn.execute("SELECT raw_data FROM listings").fetchall()
        }
    assert tags == {"residential", "commercial", "holiday", "projects"}


def test_reimport_produces_zero_duplicates(db, tmp_path):
    first = _run_all(db, _client(tmp_path))
    total_after_first = _count(db, "SELECT count(*) FROM listings")

    second = _run_all(db, _client(tmp_path))

    assert _count(db, "SELECT count(*) FROM listings") == total_after_first
    for category in ("residential", "commercial", "holiday", "projects"):
        assert second[category].inserted == 0
        assert second[category].updated == first[category].inserted


def test_project_maps_to_one_listing_with_min_plan_price(db, tmp_path):
    _run_all(db, _client(tmp_path))
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT price, raw_data FROM listings WHERE raw_data->>'propdata_category' = 'projects'"
        ).fetchall()
    assert len(rows) == 3  # page_limit=1 -> 3 project fixtures
    for row in rows:
        assert row["raw_data"]["propdata_plans"]  # plan detail preserved
