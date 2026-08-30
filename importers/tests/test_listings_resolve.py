"""Opt-in database tests for foreign-key resolution."""

from __future__ import annotations

import os

import pytest

from iol_importers.listings._scratch import scratch_schema
from iol_importers.listings.resolve import (
    MappingError,
    resolve_property_type,
    resolve_suburb,
)

pytestmark = pytest.mark.dbtest


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    with scratch_schema() as scratch:
        yield scratch


def _feed_id(conn) -> int:
    return conn.execute("SELECT id FROM feed_sources WHERE code = 'demo-feed'").fetchone()["id"]


def test_property_type_name_hit_persists_a_mapping(db):
    with db.connect() as conn:
        feed_id = _feed_id(conn)
        with conn.cursor() as cur:
            first = resolve_property_type(cur, feed_id, "house")
            second = resolve_property_type(cur, feed_id, "house")
        conn.commit()

        mappings = conn.execute(
            "SELECT vendor_value, property_type_id FROM property_type_vendor_mappings"
        ).fetchall()

    assert first == second
    assert len(mappings) == 1
    assert mappings[0]["vendor_value"] == "house"
    assert mappings[0]["property_type_id"] == first


def test_property_type_true_miss_raises_mapping_error(db):
    with db.connect() as conn:
        feed_id = _feed_id(conn)
        with conn.cursor() as cur, pytest.raises(MappingError):
            resolve_property_type(cur, feed_id, "Spaceship")


def test_vendor_listing_type_namespaces_the_mapping_key(db):
    with db.connect() as conn:
        feed_id = _feed_id(conn)
        with conn.cursor() as cur:
            res = resolve_property_type(cur, feed_id, "Apartment", "residential")
            com = resolve_property_type(cur, feed_id, "Apartment", "commercial")
        conn.commit()
        keys = {
            r["vendor_value"]
            for r in conn.execute(
                "SELECT vendor_value FROM property_type_vendor_mappings"
            ).fetchall()
        }
    # both resolved via the bare-name fallback, but each persisted a namespaced row
    assert res == com
    assert keys == {"residential:Apartment", "commercial:Apartment"}


def test_suburb_direct_and_alternate_name(db):
    with db.connect() as conn, conn.cursor() as cur:
        assert resolve_suburb(cur, "Claremont") is not None
        assert resolve_suburb(cur, "Sandton CBD") == resolve_suburb(cur, "Sandton")
        assert resolve_suburb(cur, "Nowhere At All") is None
