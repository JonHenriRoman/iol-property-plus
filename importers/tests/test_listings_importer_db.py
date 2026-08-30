"""Opt-in database tests for the listing importer.

Skipped unless TEST_DATABASE_URL is set. Runs against a throwaway schema
(``listings_scratch_<pid>``) dropped CASCADE at teardown — never touches
iol_property_plus.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import copy
import os
from typing import Any

import pytest

from iol_importers.listings._scratch import ScratchDB, scratch_schema
from iol_importers.listings.importer import import_listings

pytestmark = pytest.mark.dbtest

FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    with scratch_schema() as scratch:
        yield scratch


def _import(db: ScratchDB, batch: list[dict[str, Any]], **kw):
    return import_listings(
        copy.deepcopy(batch),
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        **kw,
    )


def _count(db: ScratchDB, sql: str) -> int:
    with db.connect() as conn:
        return conn.execute(sql).fetchone()["count"]


def _valid_batch() -> list[dict[str, Any]]:
    return [
        {"vendor_listing_id": "L-1", "listing_type": "For Sale", "property_type": "House",
         "suburb": "Claremont", "price": "2500000", "title": "A"},
        {"vendor_listing_id": "L-2", "listing_type": "To Let", "property_type": "Apartment",
         "suburb": "Rondebosch", "price": "18000", "title": "B"},
        {"vendor_listing_id": "L-3", "listing_type": "Sale", "property_type": "Townhouse",
         "suburb": "Sandton", "price": "4200000", "title": "C"},
        {"vendor_listing_id": "L-4", "listing_type": "Sale", "property_type": "House",
         "suburb": "Sandton CBD", "price": "3100000", "title": "D"},
        {"vendor_listing_id": "L-5", "listing_type": "Rental", "property_type": "Apartment",
         "suburb": "Nowhere Gardens", "price": "12000", "title": "E"},
    ]


def test_two_pass_import_creates_no_duplicates_or_extra_history(db: ScratchDB):
    batch = _valid_batch()

    first = _import(db, batch)
    assert (first.seen, first.inserted, first.updated, first.failed) == (5, 5, 0, 0)
    assert _count(db, "SELECT count(*) FROM listings") == 5
    assert _count(db, "SELECT count(*) FROM listing_price_history") == 5  # one 'Initial' each

    second = _import(db, batch)
    assert (second.seen, second.inserted, second.updated, second.failed) == (5, 0, 5, 0)
    assert _count(db, "SELECT count(*) FROM listings") == 5
    assert _count(db, "SELECT count(*) FROM listing_price_history") == 5  # unchanged
    assert _count(db, "SELECT count(*) FROM import_jobs") == 2


def test_malformed_record_is_isolated(db: ScratchDB):
    batch = [
        {"vendor_listing_id": "OK-1", "listing_type": "Sale", "property_type": "House",
         "suburb": "Claremont", "price": "1000000", "title": "fine"},
        {"vendor_listing_id": "BAD-parse", "listing_type": "Sale", "property_type": "House",
         "suburb": "Claremont", "price": "1000000", "bedrooms": "lots", "title": "junk beds"},
        {"vendor_listing_id": "BAD-map", "listing_type": "Sale", "property_type": "Castle",
         "suburb": "Claremont", "price": "1000000", "title": "unknown type"},
        {"vendor_listing_id": "OK-2", "listing_type": "Rental", "property_type": "Apartment",
         "suburb": "Rondebosch", "price": "9000", "title": "also fine"},
    ]
    counts = _import(db, batch)
    assert (counts.seen, counts.inserted, counts.failed) == (4, 2, 2)
    assert _count(db, "SELECT count(*) FROM listings") == 2

    with db.connect() as conn:
        errors = conn.execute(
            "SELECT vendor_listing_id, error_type FROM import_errors ORDER BY vendor_listing_id"
        ).fetchall()
        status = conn.execute(
            "SELECT status FROM import_jobs ORDER BY id DESC LIMIT 1"
        ).fetchone()["status"]

    assert {(e["vendor_listing_id"], e["error_type"]) for e in errors} == {
        ("BAD-parse", "parse"),
        ("BAD-map", "mapping"),
    }
    assert status == "PartialSuccess"


def test_price_change_writes_exactly_one_history_row(db: ScratchDB):
    batch = _valid_batch()
    _import(db, batch)
    base_history = _count(db, "SELECT count(*) FROM listing_price_history")

    dropped = copy.deepcopy(batch)
    dropped[0]["price"] = "2300000"
    _import(db, dropped)

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT h.old_price, h.new_price, h.change_type, h.import_job_id
            FROM listing_price_history h
            JOIN listings l ON l.id = h.listing_id
            WHERE l.vendor_listing_id = 'L-1' AND h.change_type <> 'Initial'
            """
        ).fetchall()
        last_job = conn.execute("SELECT max(id) AS id FROM import_jobs").fetchone()["id"]

    assert _count(db, "SELECT count(*) FROM listing_price_history") == base_history + 1
    assert len(rows) == 1
    assert rows[0]["old_price"] == 2500000
    assert rows[0]["new_price"] == 2300000
    assert rows[0]["change_type"] == "Decrease"
    assert rows[0]["import_job_id"] == last_job

    _import(db, dropped)  # same price again
    assert _count(db, "SELECT count(*) FROM listing_price_history") == base_history + 1


def test_unresolved_suburb_is_null_not_an_error(db: ScratchDB):
    _import(db, [{"vendor_listing_id": "N-1", "listing_type": "Sale", "property_type": "House",
                 "suburb": "Atlantis of the Deep", "price": "1", "title": "x"}])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT suburb_id FROM listings WHERE vendor_listing_id = 'N-1'"
        ).fetchone()
    assert row["suburb_id"] is None
    assert _count(db, "SELECT count(*) FROM import_errors") == 0


def test_alternate_name_resolves_suburb(db: ScratchDB):
    _import(db, [{"vendor_listing_id": "ALT-1", "listing_type": "Sale", "property_type": "House",
                 "suburb": "Sandhurst", "price": "1", "title": "x"}])
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT s.name FROM listings l JOIN suburbs s ON s.id = l.suburb_id
            WHERE l.vendor_listing_id = 'ALT-1'
            """
        ).fetchone()
    assert row["name"] == "Sandton"


def test_agency_and_agent_are_reused_across_records(db: ScratchDB):
    batch = [
        {"vendor_listing_id": "R-1", "listing_type": "Sale", "property_type": "House",
         "suburb": "Claremont", "price": "1", "title": "one",
         "agency_vendor_id": "V-9", "agency_name": "Acme", "agent_vendor_id": "P-9",
         "agent_name": "Sam Jones"},
        {"vendor_listing_id": "R-2", "listing_type": "Sale", "property_type": "House",
         "suburb": "Claremont", "price": "1", "title": "two",
         "agency_vendor_id": "V-9", "agency_name": "Acme", "agent_vendor_id": "P-9",
         "agent_name": "Sam Jones"},
    ]
    _import(db, batch)
    assert _count(db, "SELECT count(*) FROM agencies") == 1
    assert _count(db, "SELECT count(*) FROM agency_vendor_ids") == 1
    assert _count(db, "SELECT count(*) FROM agents") == 1
    assert _count(db, "SELECT count(*) FROM agent_vendor_ids") == 1

    with db.connect() as conn:
        agent = conn.execute("SELECT first_name, last_name FROM agents").fetchone()
    assert (agent["first_name"], agent["last_name"]) == ("Sam", "Jones")


def test_missing_title_is_a_validation_error(db: ScratchDB):
    counts = _import(db, [{"vendor_listing_id": "T-1", "listing_type": "Sale",
                           "property_type": "House", "suburb": "Claremont", "price": "1"}])
    assert (counts.inserted, counts.failed) == (0, 1)
    with db.connect() as conn:
        err = conn.execute("SELECT error_type FROM import_errors").fetchone()
    assert err["error_type"] == "validation"


def test_unpromoted_fields_land_in_raw_data(db: ScratchDB):
    _import(db, [{"vendor_listing_id": "RD-1", "listing_type": "Sale", "property_type": "House",
                 "suburb": "Claremont", "price": "1", "title": "x",
                 "vendor_internal_ref": "ABC123", "weird_flag": True}])
    with db.connect() as conn:
        raw = conn.execute(
            "SELECT raw_data FROM listings WHERE vendor_listing_id = 'RD-1'"
        ).fetchone()["raw_data"]
    assert raw == {"vendor_internal_ref": "ABC123", "weird_flag": True}
