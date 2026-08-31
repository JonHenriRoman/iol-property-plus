"""MyRoof BracketRecord -> import_listings record mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.bracket_kv import BracketRecord, parse
from iol_importers.myroof.map import _clean_description, _split_gps, to_import_record

FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/myroof/fixtures/feed.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "myroof.txt"


def _by_ref() -> dict[str, BracketRecord]:
    return {r.get("Reference"): r for r in parse(FIXTURE.read_text())}


def test_core_fields_and_p_tag_cleanup():
    rec = _by_ref()["MR149308"]
    out, images = to_import_record(rec)
    assert out["vendor_listing_id"] == "MR149308"
    assert out["title"] == "3 Bedroom House For Sale in Rustenburg"
    assert out["property_type"] == "House"
    assert out["listing_type"] == "For Sale"
    assert out["price"] == "850000"
    assert out["price_on_application"] is False
    assert out["bedrooms"] == "3"
    assert out["garages"] == "2"
    assert out["floor_size"] == "180"
    assert out["erf_size"] == "991"
    assert (out["latitude"], out["longitude"]) == ("-25.795631318358001", "27.243352532387")
    assert images[0].endswith("3455541.jpg")

    desc = out["description"]
    assert "<p>" not in desc
    assert "</p>" not in desc
    assert desc.startswith("Bank-repossessed 3 bedroom family home")
    assert "\n\n" in desc  # paragraph breaks became blank lines
    assert desc == desc.strip()


def test_gps_sentinel_and_helper():
    assert _split_gps("-25.8,28.1") == ("-25.8", "28.1")
    assert _split_gps(",") == (None, None)
    assert _split_gps("") == (None, None)
    assert _split_gps(None) == (None, None)
    out, _ = to_import_record(_by_ref()["MR706715"])
    assert (out["latitude"], out["longitude"]) == (None, None)


def test_price_zero_and_missing_are_price_on_application():
    out, _ = to_import_record(_by_ref()["MR300001"])  # Price:0.00
    assert out["price"] is None
    assert out["price_on_application"] is True


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("MR149308", "House"),
        ("MR706715", "House"),  # Freehold Residence -> House
        ("MR300001", "Townhouse"),  # Complex -> Townhouse
        ("MR300003", "Apartment"),  # Open Plan Bachelor/Studio Apartment (literal /)
        ("MR300004", "Vacant Land"),  # Plot -> Vacant Land
    ],
)
def test_type_crosswalk(ref, expected):
    out, _ = to_import_record(_by_ref()[ref])
    assert out["property_type"] == expected


def test_unmapped_type_passes_through_for_the_importer_to_reject():
    out, _ = to_import_record(_by_ref()["MR300002"])  # Guest House
    assert out["property_type"] == "Guest House"  # raw -> resolve_property_type -> MappingError


def test_agent_name_is_the_program_label_and_email_is_the_id():
    out, _ = to_import_record(_by_ref()["MR149308"])
    assert out["agent_name"] == "Standard Bank Repossessed"
    assert out["agent_vendor_id"] == "sbsa_repo@myroof.co.za"
    assert out["myroof_agent_program"] == "Standard Bank Repossessed"
    assert out["agency_vendor_id"] == "1"
    assert out["agency_name"] == "MyRoof.co.za"


def test_features_always_include_repossession():
    out, _ = to_import_record(_by_ref()["MR706715"])  # Pool:1, Staff_Accomm:Yes, Garden:No
    assert out["features"] == ["Staff Accommodation", "Pool", "Repossession"]
    out2, _ = to_import_record(_by_ref()["MR300004"])  # no flags
    assert out2["features"] == ["Repossession"]


def test_video_url_and_unknown_keys_land_in_raw_data():
    out, _ = to_import_record(_by_ref()["MR706715"])
    assert out["myroof_Video_URL"] == [
        "https://www.youtube.com/watch?v=abc123",
        "https://tour.cloudpano.com/tours/xyz789",
    ]
    assert out["myroof_Carports"] == "2"
    assert out["myroof_Study"] == "1"
    # Kitchens is a plain count, kept as-is (never list-parsed like RT3)
    assert out["myroof_Kitchens"] == "1"

    out4, _ = to_import_record(_by_ref()["MR300004"])
    assert out4["myroof_Solar"] == "Yes"  # unknown key captured, not dropped


def test_listed_timestamp_passes_through():
    out, _ = to_import_record(_by_ref()["MR149308"])
    assert out["listed_at"] == "2016-11-01 08:41:51.000"


def test_clean_description_unescapes_entities():
    assert _clean_description("<p>a &amp; b</p><p>c</p>") == "a & b\n\nc"
    assert _clean_description("plain <br/> break") == "plain\n break"
    assert _clean_description("") is None
    assert _clean_description(None) is None


def test_real_two_record_extract_maps_clean():
    records = parse(REAL.read_text())
    assert len(records) == 2
    for rec in records:
        out, _ = to_import_record(rec)
        assert out["vendor_listing_id"].startswith("MR")
        assert out["property_type"] == "House"  # House / Freehold Residence
        assert "Repossession" in out["features"]
        assert "__validation_error__" not in out
