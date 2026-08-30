"""Runnable proof of the listing importer — the objective's two-pass test import.

Builds the Domain 4 scratch schema on ``TEST_DATABASE_URL``, seeds reference data,
then runs the same batch three times: as-is, again unchanged, and once more with
one listing's price dropped. Prints the counts and row totals after each pass, and
the price-history row the change produced.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.listings.demo
"""

from __future__ import annotations

import copy
import json
from typing import Any

from ._scratch import ScratchDB, scratch_schema
from .importer import import_listings

FEED = "demo-feed"

_BATCH: list[dict[str, Any]] = [
    {
        "vendor_listing_id": "L-001",
        "listing_type": "For Sale",
        "property_type": "House",
        "suburb": "Claremont",
        "agency_vendor_id": "AG-1",
        "agency_name": "Seaboard Realty",
        "agent_vendor_id": "A-11",
        "agent_name": "Jane Smith",
        "price": "2 500 000",
        "bedrooms": "3",
        "bathrooms": "2.5",
        "title": "Family home in Claremont",
        "features": ["Pool", "Solar"],
        "vendor_ref_code": "SR-CLA-001",  # not promoted -> raw_data
    },
    {
        "vendor_listing_id": "L-002",
        "listing_type": "4 Rent",
        "property_type": "Apartment",
        "suburb": "Rondebosch",
        "agency_vendor_id": "AG-1",
        "agency_name": "Seaboard Realty",
        "agent_vendor_id": "A-11",
        "agent_name": "Jane Smith",
        "price": "R18,000",
        "bedrooms": "2",
        "title": "Modern apartment near UCT",
    },
    {
        "vendor_listing_id": "L-003",
        "listing_type": "SALE",
        "property_type": "Townhouse",
        "suburb": "Sandton",
        "agency_vendor_id": "AG-2",
        "agency_name": "Highveld Properties",
        "price": "4200000",
        "title": "Townhouse in a secure estate",
    },
    {
        "vendor_listing_id": "L-004",
        "listing_type": "For Sale",
        "property_type": "House",
        "suburb": "Sandton CBD",  # resolves via alternate_names -> Sandton
        "agency_vendor_id": "AG-2",
        "agency_name": "Highveld Properties",
        "price": "3100000",
        "title": "House near the Sandton CBD",
    },
    {
        "vendor_listing_id": "L-005",
        "listing_type": "For Sale",
        "property_type": "Mansion",  # no property_types match -> mapping error
        "suburb": "Claremont",
        "price": "9000000",
        "title": "Sprawling estate",
    },
    {
        "vendor_listing_id": "L-006",
        "listing_type": "Rental",
        "property_type": "Apartment",
        "suburb": "Nowhere Gardens",  # unresolved -> suburb_id NULL, still imports
        "price": "12000",
        "title": "Apartment somewhere",
    },
]


def _totals(db: ScratchDB) -> dict[str, int]:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM listings) AS listings,
                (SELECT count(*) FROM import_errors) AS import_errors,
                (SELECT count(*) FROM listing_price_history) AS price_history,
                (SELECT count(DISTINCT (feed_source_id, vendor_listing_id))
                   FROM listings) AS unique_keys
            """
        ).fetchone()
    return row


def _pass(db: ScratchDB, label: str, batch: list[dict[str, Any]]) -> None:
    counts = import_listings(
        copy.deepcopy(batch),
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        file_reference=f"{label}.json",
    )
    print(f"\n{label}: {counts}")
    print(f"  totals: {_totals(db)}")


def main() -> int:
    with scratch_schema() as db:
        _pass(db, "pass-1 (initial)", _BATCH)
        _pass(db, "pass-2 (identical re-import)", _BATCH)

        dropped = copy.deepcopy(_BATCH)
        dropped[0]["price"] = "2300000"  # L-001: 2,500,000 -> 2,300,000
        _pass(db, "pass-3 (L-001 price drop)", dropped)

        with db.connect() as conn:
            rows = conn.execute(
                """
                SELECT h.old_price, h.new_price, h.change_type, h.import_job_id, l.vendor_listing_id
                FROM listing_price_history h
                JOIN listings l ON l.id = h.listing_id
                WHERE h.change_type <> 'Initial'
                ORDER BY h.id
                """
            ).fetchall()
        print("\nnon-initial listing_price_history rows:")
        for row in rows:
            print("  " + json.dumps(row, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
