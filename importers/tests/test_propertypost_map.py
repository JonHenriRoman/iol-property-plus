"""PropertyPost BracketRecord -> import_listings record mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.bracket_kv import BracketRecord, parse
from iol_importers.propertypost.map import _coalesce_pair, _split_gps, to_import_record

FIXTURE = Path(__file__).resolve().parents[1] / "src/iol_importers/propertypost/fixtures/feed.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "propertypost.txt"


def _records() -> list[BracketRecord]:
    return parse(FIXTURE.read_text())


def _by_ref() -> dict[str, BracketRecord]:
    # last occurrence wins — fine, the duplicate is byte-identical
    return {r.get("Reference"): r for r in _records()}


def test_core_fields():
    out, images = to_import_record(_by_ref()["5084381"])
    assert out["vendor_listing_id"] == "5084381"
    assert out["title"] == "Stunning low-maintenance house for sale in Doringkloof"
    assert out["property_type"] == "House"
    assert out["listing_type"] == "For Sale"
    assert out["price"] == "2050000.00"
    assert out["price_on_application"] is False
    assert out["bedrooms"] == "3.00"
    assert out["bathrooms"] == "2.00"
    assert out["garages"] == "1"
    assert out["parking_spaces"] == "1"
    assert out["floor_size"] == "220"
    assert out["erf_size"] == "991"
    assert out["street_address"] == "12 Panorama Road, CENTURION, DORINGKLOOF"
    assert (out["latitude"], out["longitude"]) == ("-25.854917", "28.206539")
    assert out["listed_at"] == "2022-10-10 12:41:48"
    assert out["vendor_updated_at"] == "2022-10-10 16:14:22"
    assert images[0].endswith("6343fb37-7844-419e-abe6-4bdc81e8fb54.jpg")
    assert "<p>" not in (out["description"] or "")


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("5073542", "Commercial"),
        ("5084381", "House"),
        ("5090001", "Townhouse"),
        ("5090002", "Apartment"),  # Apartment Or Flat
        ("5090003", "Apartment"),  # Flat
        ("5090004", "Vacant Land"),  # Stand
        ("5090005", "Farm"),  # Smallholding
    ],
)
def test_type_crosswalk(ref, expected):
    out, _ = to_import_record(_by_ref()[ref])
    assert out["property_type"] == expected


def test_unmapped_type_passes_through_for_the_importer_to_reject():
    rec = parse(
        "[[Listing_Start]]\n[[Reference:X1/]]\n[[Heading:h/]]\n[[Type:Time Share/]]\n"
        "[[Status:For Sale/]]\n[[Listing_End]]"
    )[0]
    out, _ = to_import_record(rec)
    assert out["property_type"] == "Time Share"


def test_coalesce_pair_helper():
    def rec(**kw):
        body = "[[Listing_Start]]\n" + "".join(f"[[{k}:{v}/]]\n" for k, v in kw.items())
        return parse(body + "[[Listing_End]]")[0]

    assert _coalesce_pair(rec(Bedrooms="3.00", Beds="3.00"), "Bedrooms", "Beds") == ("3.00", None)
    # blank primary falls back to secondary, no conflict
    assert _coalesce_pair(rec(Bedrooms="", Beds="2.00"), "Bedrooms", "Beds") == ("2.00", None)
    # blank secondary is fine
    assert _coalesce_pair(rec(Bedrooms="4.00", Beds=""), "Bedrooms", "Beds") == ("4.00", None)
    # genuine numeric disagreement -> conflict string
    value, conflict = _coalesce_pair(rec(Bedrooms="4.00", Beds="3.00"), "Bedrooms", "Beds")
    assert value == "4.00"
    assert conflict == "Bedrooms=4.00 Beds=3.00"


def test_blank_beds_with_bedrooms_set_coalesces_without_conflict():
    out, _ = to_import_record(_by_ref()["5090001"])  # Beds:'' Bedrooms:2.00
    assert out["bedrooms"] == "2.00"
    assert "__field_conflicts__" not in out
    assert "propertypost_bedrooms_conflict" not in out


def test_divergent_bedroom_pair_is_flagged_not_silently_dropped():
    out, _ = to_import_record(_by_ref()["5090004"])  # Beds:3.00 vs Bedrooms:4.00
    assert out["bedrooms"] == "4.00"
    assert out["__field_conflicts__"] == ["bedrooms"]
    assert out["propertypost_bedrooms_conflict"] == "Bedrooms=4.00 Beds=3.00"


def test_gps_absent_is_none_with_no_sentinel_logic():
    assert _split_gps(None) == (None, None)
    assert _split_gps("-25.8,28.1") == ("-25.8", "28.1")
    out, _ = to_import_record(_by_ref()["5073542"])  # no GPS key
    assert (out["latitude"], out["longitude"]) == (None, None)


def test_price_zero_and_missing_are_price_on_application():
    out, _ = to_import_record(_by_ref()["5090003"])  # Price:0.00
    assert out["price"] is None
    assert out["price_on_application"] is True


def test_erf_size_zero_becomes_none():
    out, _ = to_import_record(_by_ref()["5090003"])  # Erf_Size:0
    assert out["erf_size"] is None


def test_title_synthesized_from_description_then_from_type_and_suburb():
    from_desc, _ = to_import_record(_by_ref()["5090002"])  # blank Heading, has Description
    assert from_desc["title"] == "Modern two-bed apartment in a secure Sunninghill complex."

    from_type, _ = to_import_record(_by_ref()["5090001"])  # blank Heading and Description
    assert from_type["title"] == "Townhouse in Doringkloof"


def test_yes_flags_become_feature_labels():
    out, _ = to_import_record(_by_ref()["5084381"])
    assert set(out["features"]) == {
        "Study",
        "Pool",
        "Alarm",
        "Patio",
        "Kitchen",
        "Reception Room",
        "Garden",
        "Family Room",
    }
    # Kitchens: YES is a boolean feature here, never a count
    assert "Kitchen" in out["features"]
    bare, _ = to_import_record(_by_ref()["5090004"])  # no flags
    assert bare["features"] == []


def test_admin_id_is_kept_as_company_contact_never_as_the_agent():
    out, _ = to_import_record(_by_ref()["5084381"])
    assert out["agent_vendor_id"] == "pierredk.admin@bstproperties.co.za"
    assert out["agent_name"] == "Pierre de Kock"
    assert out["propertypost_admin_email"] == "brendan@bstproperties.co.za"
    assert out["agent_vendor_id"] != out["propertypost_admin_email"]


def test_features_description_kept_verbatim_and_empty_produces_no_key():
    with_text, _ = to_import_record(_by_ref()["5090002"])
    assert with_text["propertypost_Features_Description"] == (
        "Access Gate - YES - 24hr security   Electric Fencing - YES - 3,3km "
        "surrounding estate   Levies - 600 - Levy does not increase per year"
    )
    empty, _ = to_import_record(_by_ref()["5073542"])  # Features_Description:/
    assert "propertypost_Features_Description" not in empty


def test_unknown_key_and_counts_land_in_raw_data():
    out, _ = to_import_record(_by_ref()["5090002"])
    assert out["propertypost_Solar"] == "YES"  # unknown key captured, not dropped
    house, _ = to_import_record(_by_ref()["5084381"])
    assert house["propertypost_Living_Rooms"] == "1"
    assert house["propertypost_Ensuites"] == "1"
    assert house["propertypost_Levels"] == "1"


def test_agency_is_per_record_from_branch_fields():
    out, _ = to_import_record(_by_ref()["5073542"])
    assert out["agency_vendor_id"] == "39350"
    assert out["agency_name"] == "BST PROPERTIES (PTY) LTD"


def test_real_two_record_extract_maps_clean():
    records = parse(REAL.read_text())
    assert len(records) == 2
    rentals = 0
    for rec in records:
        out, _ = to_import_record(rec)
        assert out["vendor_listing_id"]
        assert out["title"]
        assert "__validation_error__" not in out
        if out["listing_type"] == "To Let":
            rentals += 1
            assert (out["latitude"], out["longitude"]) == (None, None)  # no GPS
            assert "propertypost_Features_Description" not in out  # empty
    assert rentals == 1
