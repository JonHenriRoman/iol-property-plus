"""Webbox Property -> import_listings record mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.webbox.features import size_to_sqm
from iol_importers.webbox.map import to_import_record
from iol_importers.webbox.parse import parse_feed

FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/webbox/fixtures/feed.xml"


def _by_ref() -> dict:
    return {p.fields["reference"]: p for p in parse_feed(FIXTURE.read_bytes()).properties}


def test_sale_record_core_fields():
    out, images = to_import_record(_by_ref()["1531"])
    assert out["vendor_listing_id"] == "1531"
    assert out["title"] == "4 Bedroom home for SALE in Dwarskersbos Kersbosstrand"
    assert out["property_type"] == "House"
    assert out["listing_type"] == "Sale"
    assert out["price"] == "3950000"
    assert out["price_on_application"] is False
    assert out["bedrooms"] == "4"
    assert out["bathrooms"] == "4.5"  # decimal survives
    assert out["garages"] == "2"
    assert out["rates_and_taxes"] == "1300"  # <taxes> -> rates_and_taxes
    assert out["erf_size"] == "589"  # land-size
    assert "floor_size" not in out or out["floor_size"] is None
    assert out["street_address"] == "27 Moregloed Kersbosstrand  Dwarskersbos"
    assert "webbox_periodicity" not in out  # Sale has no periodicity
    assert len(images) == 3


def test_rent_record_has_periodicity_and_property_size():
    out, _ = to_import_record(_by_ref()["1597"])
    assert out["listing_type"] == "Rent"
    assert out["floor_size"] == "74"  # property-size
    assert out.get("erf_size") is None
    assert out["webbox_currency"] == "ZAR"
    assert out["webbox_periodicity"] == "Per month"
    assert (out["latitude"], out["longitude"]) == ("-33.8615699", "18.5186482")
    assert "Availability: 2025-05-01" in out["description"]


def test_empty_amount_is_price_on_application():
    out, _ = to_import_record(_by_ref()["2678"])
    assert out["price"] is None
    assert out["price_on_application"] is True
    assert out["webbox_periodicity"] == "Per day"


def test_multi_agent_first_drives_the_columns_full_roster_in_raw_data():
    out, _ = to_import_record(_by_ref()["1531"])
    assert out["agent_vendor_id"] == "20733"
    assert out["agent_name"] == "Leonard Smallbones"
    roster = out["webbox_agents"]
    assert [a["agent_id"] for a in roster] == ["20733", "20734"]
    assert roster[1]["email"] == "donavan@valuables.co.za"
    assert roster[0]["bio"].startswith("Leonard Smallbones is the Principal")


def test_agency_comes_from_agency_details():
    out, _ = to_import_record(_by_ref()["1597"])
    assert out["agency_vendor_id"] == "612"
    assert out["agency_name"] == "Valuables Properties - Bellville"
    assert out["webbox_agency"]["email"] == "info@valuables.co.za"


def test_non_zar_currency_is_rejected():
    out, _ = to_import_record(_by_ref()["9001"])
    assert out["webbox_currency"] == "USD"
    assert out["__validation_error__"].startswith("non-ZAR currency 'USD'")


def test_non_sa_country_is_kept_not_rejected():
    out, _ = to_import_record(_by_ref()["9002"])
    assert out["webbox_country"] == "Namibia"
    assert "__validation_error__" not in out  # imported; quarantine happens later on property_type


def test_unmapped_property_type_passes_through_for_the_importer_to_reject():
    out, _ = to_import_record(_by_ref()["9002"])
    assert out["property_type"] == "Boat House"


def test_unknown_feature_tag_lands_in_raw_data():
    out, _ = to_import_record(_by_ref()["9002"])
    assert out["webbox_feature_solar_geyser"] == "Yes"


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        ("74", "meters_squared", "74"),
        ("589", None, "589"),
        ("0.12", "hectares", "1200"),
        ("0.85", "HECTARES", "8500"),
        ("1", "acres", "4046.86"),
        ("", "meters_squared", None),
        ("0", "hectares", None),
    ],
)
def test_size_to_sqm(value, unit, expected):
    assert size_to_sqm(value, unit) == expected


def test_property_type_crosswalk():
    def rec(pt):
        body = (
            f"<property><reference>X</reference><heading><![CDATA[h]]></heading>"
            f"<listing-type>Sale</listing-type><price><amount>1</amount>"
            f"<currency>ZAR</currency></price><property-type>{pt}</property-type></property>"
        )
        return to_import_record(parse_feed(body.encode()).properties[0])[0]

    assert rec("Studio apartment")["property_type"] == "Apartment"
    assert rec("Cottage")["property_type"] == "Apartment"
    assert rec("Vacant Land / Plot")["property_type"] == "Vacant Land"
    assert rec("House")["property_type"] == "House"  # self-map
    assert rec("Chalet")["property_type"] == "Chalet"  # unmapped passthrough
