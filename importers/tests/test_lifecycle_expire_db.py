"""Opt-in database tests for the expiry sweep.

Skipped unless TEST_DATABASE_URL is set. Runs against the listings scratch schema
(``listings_scratch_<pid>``, dropped CASCADE) — never touches iol_property_plus.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import pytest

from iol_importers.lifecycle.expire import expire_listings

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _seed_listing(db, vendor_id: str, *, status: str = "Active", past_days: int = 1) -> None:
    """Insert a listing, then force status + expires_at without touching
    last_seen_at (so trg_listings_set_expiry stays a no-op)."""
    with db.connect(autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO listings (feed_source_id, vendor_listing_id, property_type_id,
                                  listing_type, title)
            VALUES ((SELECT id FROM feed_sources WHERE code = %s), %s,
                    (SELECT id FROM property_types WHERE name = 'House'), 'Sale', %s)
            """,
            (FEED, vendor_id, f"Listing {vendor_id}"),
        )
        conn.execute(
            """
            UPDATE listings SET status = %s, expires_at = now() - make_interval(days => %s)
            WHERE vendor_listing_id = %s
            """,
            (status, past_days, vendor_id),
        )


def _row(db, vendor_id: str) -> dict:
    with db.connect() as conn:
        return conn.execute(
            "SELECT status::text AS status, expired_at, updated_at "
            "FROM listings WHERE vendor_listing_id = %s",
            (vendor_id,),
        ).fetchone()


def test_past_expiry_active_listing_is_expired(db):
    _seed_listing(db, "L-1", status="Active", past_days=2)
    before = _row(db, "L-1")

    result = expire_listings(connect=db.data_connect)

    assert result.expired_count == 1
    after = _row(db, "L-1")
    assert after["status"] == "Expired"
    assert after["expired_at"] is not None
    assert after["updated_at"] > before["updated_at"]


def test_future_expiry_active_listing_is_untouched(db):
    _seed_listing(db, "L-future", status="Active", past_days=-5)  # 5 days in the future
    result = expire_listings(connect=db.data_connect)
    assert result.expired_count == 0
    assert _row(db, "L-future")["status"] == "Active"


def test_sold_listing_is_untouched_even_if_past_expiry(db):
    _seed_listing(db, "L-sold", status="Sold", past_days=3)
    expire_listings(connect=db.data_connect)
    row = _row(db, "L-sold")
    assert row["status"] == "Sold"
    assert row["expired_at"] is None


def test_reimported_listing_is_never_expired(db):
    from iol_importers.listings.importer import import_listings

    _seed_listing(db, "L-reimport", status="Active", past_days=1)  # would expire

    # A fresh import run refreshes expires_at into the future (via the trigger).
    import_listings(
        [{"vendor_listing_id": "L-reimport", "listing_type": "Sale",
          "property_type": "House", "suburb": "Claremont", "title": "L-reimport"}],
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )

    result = expire_listings(connect=db.data_connect)
    assert result.expired_count == 0
    assert _row(db, "L-reimport")["status"] == "Active"


def test_idempotent_second_run_changes_nothing(db):
    _seed_listing(db, "L-a", status="Active", past_days=2)
    _seed_listing(db, "L-b", status="Active", past_days=4)

    first = expire_listings(connect=db.data_connect)
    assert first.expired_count == 2

    second = expire_listings(connect=db.data_connect)
    assert second.expired_count == 0
    assert second.status_before == second.status_after


def test_status_maps_are_accurate(db):
    _seed_listing(db, "P-1", status="Active", past_days=2)
    _seed_listing(db, "P-2", status="Active", past_days=2)
    _seed_listing(db, "F-1", status="Active", past_days=-3)

    result = expire_listings(connect=db.data_connect)
    assert result.status_before == {"Active": 3}
    assert result.status_after == {"Active": 1, "Expired": 2}
