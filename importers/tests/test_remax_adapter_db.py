"""Opt-in DB test — RE/MAX fixtures round-trip through the Step 14 importer.

Scratch schema (dropped CASCADE); the RE/MAX client is fixture-backed, so this
makes no network calls.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import json
import os

import pytest

from iol_importers.config import RemaxCredentials
from iol_importers.remax.adapter import run
from iol_importers.remax.client import RemaxClient
from remax_mock import FIXTURES, mock_transport

pytestmark = pytest.mark.dbtest

CREDS = RemaxCredentials(
    access_key="AKIATEST0000000000EX",
    secret_key="secret-000000000000000000000000000000000000",
    api_key="apikey-00000000000000000000000000000000000",
    base_url="https://ahcjbl9nbb.execute-api.eu-west-1.amazonaws.com/feeds_default",
)
FEED = "demo-feed"
DETAIL_IDS = set(json.loads((FIXTURES / "listings.json").read_text()))


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _client(tmp_path) -> RemaxClient:
    return RemaxClient(
        credentials=CREDS, transport=mock_transport(), state_dir=tmp_path, retry_base_delay=0.0
    )


def _run(db, tmp_path, **kw):
    return run(
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        client=_client(tmp_path),
        **kw,
    )


def _count(db, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def test_incremental_round_trips(db, tmp_path):
    result = _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00")
    assert result.counts.failed == 0
    assert result.counts.inserted == result.changed_seen >= len(DETAIL_IDS)
    assert _count(db, "SELECT count(*) FROM import_errors") == 0


def test_full_round_trips(db, tmp_path):
    result = _run(db, tmp_path, mode="full", max_pages=1)
    assert result.counts.failed == 0
    assert result.counts.inserted > 0
    assert _count(db, "SELECT count(*) FROM import_errors") == 0


def test_reimport_zero_duplicates(db, tmp_path):
    _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00")
    total = _count(db, "SELECT count(*) FROM listings")
    second = _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00")
    assert _count(db, "SELECT count(*) FROM listings") == total
    assert second.counts.inserted == 0


def test_unchanged_date_last_updated_is_skipped_not_reupserted(db, tmp_path):
    _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00")
    second = _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00")
    # every fixture listing has an unchanged date_last_updated on the second pass
    assert second.skipped_unchanged == second.changed_seen
    assert second.counts.seen == 0  # nothing reached the importer
    assert second.counts.updated == 0


def test_deleted_feed_soft_deletes_matching_rows_only(db, tmp_path):
    # import without the deleted pass, so the deletion is applied by the run under test
    _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00", with_deleted=False)
    total_before = _count(db, "SELECT count(*) FROM listings")

    result = _run(db, tmp_path, deleted_only=True)

    assert _count(db, "SELECT count(*) FROM listings") == total_before  # soft, not hard
    assert result.withdrawn >= 1
    assert result.withdraw_not_found >= 1  # the deleted feed also lists rows we never had
    with db.connect() as conn:
        statuses = {
            r["status"]
            for r in conn.execute("SELECT DISTINCT status FROM listings").fetchall()
        }
    assert "Withdrawn" in statuses
    assert "Active" in statuses  # non-deleted rows untouched


def test_deleted_only_mode(db, tmp_path):
    _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00", with_deleted=False)
    result = _run(db, tmp_path, deleted_only=True)
    assert result.mode == "deleted"
    assert result.withdrawn >= 1


def test_deleted_pass_is_idempotent(db, tmp_path):
    _run(db, tmp_path, mode="incremental", start_date="2020-01-01 00:00:00", with_deleted=False)
    first = _run(db, tmp_path, deleted_only=True)
    second = _run(db, tmp_path, deleted_only=True)
    assert first.withdrawn >= 1
    assert second.withdrawn == 0  # nothing left to withdraw
