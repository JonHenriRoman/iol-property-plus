"""Runnable proof of the expiry sweep — before/after listing counts by status.

Builds the Domain 4 scratch schema on ``TEST_DATABASE_URL``, seeds a spread of
listings, runs the sweep, re-imports one still-live listing, runs it again.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.lifecycle.demo
"""

from __future__ import annotations

from iol_importers.listings._scratch import ScratchDB, scratch_schema
from iol_importers.listings.importer import import_listings

from .expire import expire_listings

FEED = "demo-feed"

# (vendor_listing_id, status, expires_at offset in days: positive = past)
_SEED = [
    ("L-past-1", "Active", 3),
    ("L-past-2", "Active", 1),
    ("L-past-3", "Active", 10),
    ("L-future-1", "Active", -5),
    ("L-future-2", "Active", -30),
    ("L-sold-past", "Sold", 2),
]


def _seed(db: ScratchDB) -> None:
    with db.connect(autocommit=True) as conn:
        for vendor_id, status, past_days in _SEED:
            conn.execute(
                """
                INSERT INTO listings (feed_source_id, vendor_listing_id, property_type_id,
                                      listing_type, title)
                VALUES (
                    (SELECT id FROM feed_sources WHERE code = %s),
                    %s,
                    (SELECT id FROM property_types WHERE name = 'House'),
                    'Sale', %s
                )
                """,
                (FEED, vendor_id, f"Listing {vendor_id}"),
            )
            # Force status + expires_at without touching last_seen_at, so
            # trg_listings_set_expiry stays a no-op and the values stick.
            conn.execute(
                """
                UPDATE listings
                SET status = %s, expires_at = now() - make_interval(days => %s)
                WHERE vendor_listing_id = %s
                """,
                (status, past_days, vendor_id),
            )


def _counts(db: ScratchDB) -> dict[str, int]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT status::text AS status, count(*) AS n FROM listings GROUP BY status"
        ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def main() -> int:
    with scratch_schema() as db:
        _seed(db)
        print(f"seeded: {_counts(db)}")

        first = expire_listings(connect=db.data_connect)
        print(f"\nrun 1: expired_count={first.expired_count}")
        print(f"  before: {first.status_before}")
        print(f"  after:  {first.status_after}")

        # A still-live listing, re-imported: the importer refreshes expires_at to
        # the future. It was never at risk; prove the second run leaves it alone.
        import_listings(
            [
                {
                    "vendor_listing_id": "L-future-1",
                    "listing_type": "Sale",
                    "property_type": "House",
                    "suburb": "Claremont",
                    "title": "Listing L-future-1",
                }
            ],
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
        )

        second = expire_listings(connect=db.data_connect)
        print(f"\nrun 2 (after a re-import): expired_count={second.expired_count}")
        print(f"  before: {second.status_before}")
        print(f"  after:  {second.status_after}")
        print(
            "\nidempotent: "
            f"{second.expired_count == 0 and second.status_before == second.status_after}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
