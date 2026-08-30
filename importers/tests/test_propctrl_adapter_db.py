"""Opt-in DB test — PropCtrl fixtures round-trip through the Step 14 importer.

Scratch schema (dropped CASCADE); the PropCtrl client is fixture-backed, so this
makes no network calls.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import pytest

from iol_importers.config import PropctrlCredentials
from iol_importers.propctrl.adapter import run
from iol_importers.propctrl.client import PropctrlClient
from propctrl_mock import load_changes, load_listings, mock_transport

pytestmark = pytest.mark.dbtest

CREDS = PropctrlCredentials("u", "p", "https://api.propctrl.com")
FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _client(tmp_path) -> PropctrlClient:
    return PropctrlClient(credentials=CREDS, transport=mock_transport(), state_dir=tmp_path)


def _run(db, client, **kw):
    return run(
        feed_source_code=FEED,
        from_date="2020-01-01T00:00:00Z",
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        client=client,
        **kw,
    )


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def _active_ids() -> set[str]:
    return {str(x["listingId"]) for x in load_listings() if x["listingStatus"] == "Active"}


def test_only_active_non_removed_listings_import(db, tmp_path):
    result = _run(db, _client(tmp_path))

    assert result.counts.failed == 0
    assert result.counts.inserted == len(_active_ids())
    assert _count(db, "SELECT count(*) FROM import_errors") == 0

    removed = sum(1 for i in load_changes()["items"] if i["changeType"] == "Removed")
    assert result.removed_skipped == removed
    # fixture has Sold / Withdrawn listings among the New/Modified change items
    assert result.inactive_skipped > 0

    with db.connect() as conn:
        vendor_ids = {
            r["vendor_listing_id"]
            for r in conn.execute("SELECT vendor_listing_id FROM listings").fetchall()
        }
    assert vendor_ids == _active_ids()


def test_reimport_produces_zero_duplicates(db, tmp_path):
    first = _run(db, _client(tmp_path))
    total = _count(db, "SELECT count(*) FROM listings")

    second = _run(db, _client(tmp_path))

    assert _count(db, "SELECT count(*) FROM listings") == total
    assert second.counts.inserted == 0
    assert second.counts.updated == first.counts.inserted


def test_checkpoint_advances_only_on_a_complete_run(db, tmp_path):
    client = _client(tmp_path)
    bounded = _run(db, client, max_listings=3)
    assert bounded.checkpoint_written is False
    assert client.load_checkpoint() is None

    full = _run(db, client)
    assert full.checkpoint_written is True
    assert client.load_checkpoint() == full.next_from_date


def test_change_type_is_recorded_in_raw_data(db, tmp_path):
    _run(db, _client(tmp_path))
    with db.connect() as conn:
        rows = conn.execute("SELECT raw_data FROM listings").fetchall()
    assert rows
    assert all(r["raw_data"].get("propctrl_change_type") in {"New", "Modified"} for r in rows)
