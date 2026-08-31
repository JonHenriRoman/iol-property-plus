"""Opt-in DB test — Fusion fixtures drain through the Step 14 importer.

Scratch schema (dropped CASCADE); the Fusion client is fixture-backed, so this
makes no network calls.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import pytest

from fusion_mock import mock_transport
from iol_importers.config import FusionCredentials
from iol_importers.fusion.adapter import run
from iol_importers.fusion.client import FusionClient

pytestmark = pytest.mark.dbtest

CREDS = FusionCredentials(client_id=458, password="secret", base_url="https://fusion.test/v1/sync")
FEED = "demo-feed"

SNAPSHOT = ("snapshot_1", "snapshot_2", "snapshot_3", "drained")
FULL_STORY = ("snapshot_1", "snapshot_2", "snapshot_3", "delta_1", "drained")


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _run(db, tmp_path, sequence=SNAPSHOT, **kw):
    transport, server = mock_transport(sequence)
    client = FusionClient(
        credentials=CREDS, transport=transport, state_dir=tmp_path, retry_base_delay=0.0
    )
    try:
        result = run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=client,
            **kw,
        )
    finally:
        client.close()
    return result, server


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def _one(db, sql: str, *params):
    with db.connect() as conn:
        return conn.execute(sql, params).fetchone()


def test_first_run_drains_multi_call_snapshot(db, tmp_path):
    result, _ = _run(db, tmp_path)

    assert result.snapshot_seen and result.snapshot_completed
    assert result.batches == 3
    assert result.counts.failed == 0
    assert _count(db, "SELECT count(*) FROM import_errors") == 0
    assert _count(db, "SELECT count(*) FROM listings") == 3
    assert result.events_by_object == {
        "Office": 1,
        "Agent": 1,
        "Listing": 3,
        "AreaTree": 1,
        "Development": 1,
    }
    assert result.events_by_type == {"Snapshot": 7}

    # Office -> agency, Agent -> agent, both linked
    agency = _one(
        db,
        "SELECT a.name, a.status FROM agencies a JOIN agency_vendor_ids v ON v.agency_id = a.id "
        "WHERE v.vendor_agency_id = '4'",
    )
    assert agency["name"] == "Demo Realty — Cape Town South"
    assert agency["status"] == "Active"
    agent = _one(
        db,
        "SELECT ag.first_name, ag.agency_id FROM agents ag "
        "JOIN agent_vendor_ids v ON v.agent_id = ag.id WHERE v.vendor_agent_id = '441'",
    )
    assert agent["first_name"] == "Jordan"
    assert agent["agency_id"] is not None

    # AreaTree arrived in batch 3, after listings 100/101 in batches 1/2 -> backfilled
    assert result.suburbs_backfilled == 2
    assert (
        _one(
            db,
            "SELECT s.name FROM listings l JOIN suburbs s ON s.id = l.suburb_id "
            "WHERE l.vendor_listing_id = '100'",
        )["name"]
        == "Claremont"
    )
    assert (
        _one(
            db,
            "SELECT s.name FROM listings l JOIN suburbs s ON s.id = l.suburb_id "
            "WHERE l.vendor_listing_id = '101'",
        )["name"]
        == "Rondebosch"
    )
    assert (
        _one(db, "SELECT suburb_id FROM listings WHERE vendor_listing_id = '102'")["suburb_id"]
        is None
    )

    # commit token persisted
    from iol_importers.fusion.client import FusionClient as _C

    saved = _C(credentials=CREDS, state_dir=tmp_path).load_state()
    assert saved.commit_token == "snap-token-3"
    assert saved.snapshot.in_progress is False


def test_full_story_snapshot_then_delta(db, tmp_path):
    result, _ = _run(db, tmp_path, sequence=FULL_STORY)

    assert result.batches == 4
    assert result.snapshot_completed is True
    assert result.listings_withdrawn == 1
    assert result.refs_withdrawn == 2

    assert _count(db, "SELECT count(*) FROM listings") == 3  # soft delete, not hard
    statuses = {
        r["vendor_listing_id"]: r["status"]
        for r in _rows(db, "SELECT vendor_listing_id, status FROM listings")
    }
    assert statuses == {"100": "Active", "101": "Withdrawn", "102": "Active"}

    # delta updated 100's price
    assert (
        _one(db, "SELECT price FROM listings WHERE vendor_listing_id = '100'")["price"] == 2495000
    )

    # OfficeRef / AgentRef deletes -> status Inactive, no rows removed
    assert (
        _one(
            db,
            "SELECT a.status FROM agencies a JOIN agency_vendor_ids v ON v.agency_id = a.id "
            "WHERE v.vendor_agency_id = '4'",
        )["status"]
        == "Inactive"
    )
    assert (
        _one(
            db,
            "SELECT ag.status FROM agents ag JOIN agent_vendor_ids v ON v.agent_id = ag.id "
            "WHERE v.vendor_agent_id = '441'",
        )["status"]
        == "Inactive"
    )
    assert _count(db, "SELECT count(*) FROM agencies") == 1
    assert _count(db, "SELECT count(*) FROM agents") == 1


def test_unacknowledged_batch_replay_creates_no_duplicates(db, tmp_path):
    transport, server = mock_transport(SNAPSHOT)
    client = FusionClient(
        credentials=CREDS, transport=transport, state_dir=tmp_path, retry_base_delay=0.0
    )
    try:
        first = run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=client,
            max_batches=1,
            write_state=False,
        )
        rows_after_first = _count(db, "SELECT count(*) FROM listings")
        # token never acknowledged (write_state=False) -> server still at batch 0
        second = run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=client,
            max_batches=1,
            write_state=False,
        )
    finally:
        client.close()

    assert server.get_changes_calls == [None, None]  # both replays, no ack
    assert first.counts.inserted == rows_after_first == 1
    assert second.counts.inserted == 0
    assert _count(db, "SELECT count(*) FROM listings") == rows_after_first


def test_resume_from_saved_commit_token(db, tmp_path):
    phase1, _ = _run(db, tmp_path, max_batches=1)
    assert phase1.batches == 1
    assert _count(db, "SELECT count(*) FROM listings") == 1

    phase2, _ = _run(db, tmp_path)  # fresh client + server, same state_dir
    assert phase2.snapshot_completed is True
    assert _count(db, "SELECT count(*) FROM listings") == 3
    assert _count(db, "SELECT count(*) FROM import_errors") == 0


def test_dry_run_writes_nothing(db, tmp_path):
    result, _ = _run(db, tmp_path, dry_run=True)
    assert result.dry_run is True
    assert result.counts.seen == 3
    assert _count(db, "SELECT count(*) FROM listings") == 0
    assert _count(db, "SELECT count(*) FROM agencies") == 0
    assert FusionClient(credentials=CREDS, state_dir=tmp_path).load_state().commit_token is None


def _rows(db, sql: str):
    with db.connect() as conn:
        return conn.execute(sql).fetchall()
