"""Opt-in DB test — lifecycle.withdraw_listings soft-delete.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import pytest

from iol_importers.lifecycle.withdraw import withdraw_listings, withdraw_missing

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _seed(db, vendor_ids: list[str]) -> None:
    with db.connect() as conn:
        fsid = conn.execute("SELECT id FROM feed_sources WHERE code = %s", (FEED,)).fetchone()["id"]
        ptid = conn.execute("SELECT id FROM property_types LIMIT 1").fetchone()["id"]
        for vid in vendor_ids:
            conn.execute(
                """
                INSERT INTO listings (feed_source_id, vendor_listing_id, property_type_id, title)
                VALUES (%s, %s, %s, %s)
                """,
                (fsid, vid, ptid, f"Listing {vid}"),
            )
        conn.commit()


def _status(db, vid: str) -> str:
    with db.connect() as conn:
        return conn.execute(
            "SELECT status FROM listings WHERE vendor_listing_id = %s", (vid,)
        ).fetchone()["status"]


def test_withdraw_marks_matching_rows_and_counts_misses(db):
    _seed(db, ["A1", "A2", "A3"])
    result = withdraw_listings(FEED, ["A1", "A2", "GONE"], connect=db.data_connect)
    assert result.requested == 3
    assert result.withdrawn == 2
    assert result.not_found == 1
    assert _status(db, "A1") == "Withdrawn"
    assert _status(db, "A3") == "Active"


def test_withdraw_is_idempotent(db):
    _seed(db, ["B1"])
    first = withdraw_listings(FEED, ["B1"], connect=db.data_connect)
    second = withdraw_listings(FEED, ["B1"], connect=db.data_connect)
    assert first.withdrawn == 1
    assert second.withdrawn == 0  # already Withdrawn
    assert _status(db, "B1") == "Withdrawn"


def test_withdraw_dry_run_changes_nothing(db):
    _seed(db, ["C1"])
    result = withdraw_listings(FEED, ["C1"], connect=db.data_connect, dry_run=True)
    assert result.withdrawn == 1  # would withdraw
    assert _status(db, "C1") == "Active"


def test_withdraw_never_deletes(db):
    _seed(db, ["D1", "D2"])
    withdraw_listings(FEED, ["D1", "D2"], connect=db.data_connect)
    with db.connect() as conn:
        n = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
    assert n == 2


def _seed_scoped(db, rows: list[tuple[str, str]]) -> None:
    with db.connect() as conn:
        fsid = conn.execute("SELECT id FROM feed_sources WHERE code = %s", (FEED,)).fetchone()["id"]
        ptid = conn.execute("SELECT id FROM property_types LIMIT 1").fetchone()["id"]
        for vid, ref in rows:
            conn.execute(
                """
                INSERT INTO listings
                    (feed_source_id, vendor_listing_id, property_type_id, title, raw_data)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (fsid, vid, ptid, f"Listing {vid}", f'{{"entegral_office_reference": "{ref}"}}'),
            )
        conn.commit()


def test_withdraw_missing_scoped_to_raw_data(db):
    _seed_scoped(db, [("M1", "OFF1"), ("M2", "OFF1"), ("M3", "OFF2")])
    result = withdraw_missing(
        FEED,
        ["M1"],
        raw_scope=("entegral_office_reference", "OFF1"),
        connect=db.data_connect,
    )
    assert result.withdrawn == 1  # only M2 — M1 was seen, M3 is another office
    assert _status(db, "M1") == "Active"
    assert _status(db, "M2") == "Withdrawn"
    assert _status(db, "M3") == "Active"


def test_withdraw_missing_is_idempotent(db):
    _seed_scoped(db, [("N1", "OFF1"), ("N2", "OFF1")])
    scope = ("entegral_office_reference", "OFF1")
    first = withdraw_missing(FEED, ["N1"], raw_scope=scope, connect=db.data_connect)
    second = withdraw_missing(FEED, ["N1"], raw_scope=scope, connect=db.data_connect)
    assert first.withdrawn == 1
    assert second.withdrawn == 0


def test_withdraw_missing_dry_run_changes_nothing(db):
    _seed_scoped(db, [("P1", "OFF1"), ("P2", "OFF1")])
    result = withdraw_missing(
        FEED,
        ["P1"],
        raw_scope=("entegral_office_reference", "OFF1"),
        connect=db.data_connect,
        dry_run=True,
    )
    assert result.withdrawn == 1  # would withdraw P2
    assert _status(db, "P2") == "Active"


def test_withdraw_missing_refuses_empty_seen(db):
    _seed_scoped(db, [("Q1", "OFF1")])
    with pytest.raises(ValueError, match="empty"):
        withdraw_missing(
            FEED, [], raw_scope=("entegral_office_reference", "OFF1"), connect=db.data_connect
        )
    assert _status(db, "Q1") == "Active"
