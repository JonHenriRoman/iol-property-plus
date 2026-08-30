"""Offline tests for the Propdata -> importer-record mapping."""

from __future__ import annotations

import json

import pytest

from iol_importers.config import PropdataCredentials
from iol_importers.propdata.client import PropdataClient
from iol_importers.propdata.map import to_import_record
from propdata_mock import FIXTURES, mock_transport

CREDS = PropdataCredentials("u", "p", "https://api-gw.propdata.net/users/public-api/login/")


@pytest.fixture
def client(tmp_path) -> PropdataClient:
    c = PropdataClient(
        "harcourts.co.za", credentials=CREDS, transport=mock_transport(), token_dir=tmp_path
    )
    c.ensure_token()
    return c


def _first(category: str) -> dict:
    return json.loads((FIXTURES / f"{category}_page1.json").read_text())["results"][0]


def test_residential_core_fields(client):
    rec = to_import_record(_first("residential"), category="residential", client=client)
    raw = _first("residential")
    assert rec["vendor_listing_id"] == str(raw["id"])
    assert rec["vendor_listing_type"] == "residential"
    assert rec["listing_type"] == raw["listing_type"]  # "For Sale"
    assert rec["property_type"] == raw["property_type"]
    assert rec["title"] == raw["marketing_heading"]
    assert rec["suburb"]  # resolved via the location lookup
    assert rec["agency_vendor_id"] == str(raw["branch"])
    assert rec["agent_vendor_id"] == str(raw["agent"])


def test_commercial_is_tagged_and_keeps_its_listing_type(client):
    rec = to_import_record(_first("commercial"), category="commercial", client=client)
    assert rec["vendor_listing_type"] == "commercial"
    assert rec["listing_type"] == "To Let"


def test_holiday_is_forced_rental(client):
    raw = json.loads((FIXTURES / "holiday_page1.json").read_text())["results"][0]
    rec = to_import_record(raw, category="holiday", client=client)
    assert rec["vendor_listing_type"] == "holiday"
    assert rec["listing_type"] == "Rental"


def test_project_flattens_to_one_listing(client):
    raw = _first("projects")
    rec = to_import_record(raw, category="projects", client=client)
    assert rec["vendor_listing_type"] == "projects"
    assert rec["listing_type"] == "Sale"
    assert rec["property_type"] == "Development"
    assert rec["title"] == raw["name"]
    assert rec["bedrooms"] is None and rec["bathrooms"] is None
    plan_prices = [p["priced_from"] for p in raw["property_types"] if p.get("priced_from")]
    from decimal import Decimal

    assert Decimal(rec["price"]) == min(Decimal(p) for p in plan_prices)
    assert rec["propdata_plans"] == raw["property_types"]


def test_flagged_fields_are_not_guessed(client):
    rec = to_import_record(_first("residential"), category="residential", client=client)
    assert "latitude" not in rec and "longitude" not in rec
    assert rec["primary_image_url"] is None if "primary_image_url" in rec else True
    assert rec.get("features") in (None, [])
    # image ids are preserved verbatim for later, not turned into a URL
    assert rec["propdata_image_ids"] == _first("residential")["listing_images"]
