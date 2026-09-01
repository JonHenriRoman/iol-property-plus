"""RT3 (Rawson) BracketRecord -> import_listings record mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from iol_importers.bracket_kv import BracketRecord, parse
from iol_importers.rt3.map import _agents, _kitchen_fittings, _split_gps, to_import_record

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/rt3/fixtures"
GAUTENG = FIXTURES / "iol-Gauteng.txt"
WESTERN_CAPE = FIXTURES / "iol-Western_Cape.txt"
REAL = Path(__file__).parent / "fixtures" / "bracket_kv" / "rt3.txt"


def _by_ref(path: Path) -> dict[str, BracketRecord]:
    return {r.get("Reference"): r for r in parse(path.read_text())}


def _rec(**kw: str) -> BracketRecord:
    body = "[[Listing_Start]]\n" + "".join(f"[[{k}:{v}/]]\n" for k, v in kw.items())
    return parse(body + "[[Listing_End]]")[0]


# --- agents: zero / one / two-plus / gappy ---------------------------------


def test_zero_agents():
    out, _ = to_import_record(_by_ref(GAUTENG)["1289051"], province="Gauteng")
    assert out["agent_vendor_id"] is None
    assert out["agent_name"] is None
    assert "rt3_agents" not in out


def test_one_agent():
    out, _ = to_import_record(_by_ref(GAUTENG)["1312993"], province="Gauteng")
    assert out["agent_vendor_id"] == "bertie.cilliers@rawson.co.za"
    assert out["agent_name"] == "Bertie Cilliers"
    assert out["rt3_agents"] == [
        {"name": "Bertie Cilliers", "email": "bertie.cilliers@rawson.co.za", "cell": "0712243551"}
    ]
    assert out["rt3_co_agent_count"] == 0


def test_three_agents_first_drives_the_columns():
    out, _ = to_import_record(_by_ref(GAUTENG)["1400001"], province="Gauteng")
    assert out["agent_vendor_id"] == "thandi.nkosi@rawson.co.za"
    assert out["agent_name"] == "Thandi Nkosi"
    assert [a["name"] for a in out["rt3_agents"]] == [
        "Thandi Nkosi",
        "Pieter van der Merwe",
        "Aisha Patel",
    ]
    assert out["rt3_co_agent_count"] == 2


def test_gappy_agent_suffixes_are_ordered_by_index():
    # Agent_Name + Agent_Name_3, no _2
    out, _ = to_import_record(_by_ref(WESTERN_CAPE)["1500003"], province="Western_Cape")
    assert [a["name"] for a in out["rt3_agents"]] == ["Chantelle Fourie", "Sipho Dlamini"]
    assert out["rt3_co_agent_count"] == 1


def test_agents_helper_handles_a_bare_record():
    assert _agents(_rec(Reference="X")) == []
    roster = _agents(_rec(Agent_Name="A", Email_5="e5@x.co", Agent_Name_2="B"))
    assert [a["name"] for a in roster] == ["A", "B", None]
    assert roster[2]["email"] == "e5@x.co"


# --- images ---------------------------------------------------------------


def test_multiple_image_urls_become_multiple_ordered_records():
    _, images = to_import_record(_by_ref(GAUTENG)["1289051"], province="Gauteng")
    assert len(images) == 3
    assert images[0].endswith("67a50635-359a-47f5-b450-5ec2e76ae23e.jpg")
    assert images[-1].endswith("54bb90f5-f33e-4bc6-827d-6aae5236cbe3.jpg")


# --- GPS ----------------------------------------------------------------


def test_gps_split_and_zero_sentinel():
    assert _split_gps("-25.87711087,28.17500169") == ("-25.87711087", "28.17500169")
    assert _split_gps("0.00000000,0.00000000") == (None, None)
    assert _split_gps("0,0") == (None, None)
    assert _split_gps("") == (None, None)
    assert _split_gps(None) == (None, None)
    out, _ = to_import_record(_by_ref(GAUTENG)["1289051"], province="Gauteng")
    assert (out["latitude"], out["longitude"]) == ("-25.87711087", "28.17500169")
    office, _ = to_import_record(_by_ref(GAUTENG)["1400002"], province="Gauteng")
    assert (office["latitude"], office["longitude"]) == (None, None)


# --- Type crosswalk ------------------------------------------------------


@pytest.mark.parametrize(
    "type_raw,expected",
    [
        ("House", "House"),
        ("Commercial - Retail", "Commercial"),
        ("Commercial - Offices", "Office"),
        ("Commercial - Warehouse", "Industrial"),
        ("Commercial - Vacant Land", "Vacant Land"),
        ("Townhouse - sectional", "Townhouse"),
        ("Development", "Development"),  # self-matches the seeded row
        ("Guest House", "Guest House"),  # passthrough -> resolve_property_type quarantines
        ("Unclassified", "Unclassified"),  # passthrough -> quarantines
    ],
)
def test_type_crosswalk(type_raw, expected):
    out, _ = to_import_record(
        _rec(Reference="X", Heading="h", Type=type_raw, Status="For Sale"), province="Gauteng"
    )
    assert out["property_type"] == expected


# --- features / kitchens / counts --------------------------------------


def test_amenity_tag_lists_fold_into_features():
    out, _ = to_import_record(_by_ref(GAUTENG)["1312993"], province="Gauteng")
    feats = out["features"]
    # Security comma-list, Views, Garden all split in
    assert "alarm" in feats
    assert "automated garage door" in feats
    assert "security fencing" in feats
    assert "fairway" in feats  # Views
    assert "Garden" in feats  # Garden value is literally "Garden"
    assert "covered patio" in feats  # Patio
    assert "Alarm" in feats  # Alarm: Yes boolean


def test_boolean_amenities_and_dedupe():
    out, _ = to_import_record(_by_ref(GAUTENG)["1400001"], province="Gauteng")
    assert "Pool" in out["features"]
    assert "Staff Accommodation" in out["features"]
    assert len(out["features"]) == len(set(out["features"]))


def test_kitchens_is_parsed_as_a_token_list_not_a_feature():
    out, _ = to_import_record(_by_ref(GAUTENG)["1312993"], province="Gauteng")
    assert out["rt3_kitchen_fittings"] == [
        "extractor fan",
        "gas hob",
        "granite tops",
        "under counter oven",
    ]
    assert not any(f == "gas hob" for f in out["features"])
    assert _kitchen_fittings("_a_, _b c_") == ["a", "b c"]
    assert _kitchen_fittings("") is None


def test_numeric_counts_land_in_raw_data_never_features():
    out, _ = to_import_record(_by_ref(GAUTENG)["1312993"], province="Gauteng")
    assert out["rt3_Study"] == "1"
    assert out["rt3_Levels"] == "1"
    assert "1" not in out["features"]


# --- misc --------------------------------------------------------------


def test_price_missing_is_price_on_application():
    out, _ = to_import_record(_by_ref(WESTERN_CAPE)["1500002"], province="Western_Cape")
    assert out["price"] is None
    assert out["price_on_application"] is True


def test_listed_and_province_passthrough():
    out, _ = to_import_record(_by_ref(GAUTENG)["1312993"], province="Gauteng")
    assert out["listed_at"] == "2025-08-18"
    assert out["rt3_province"] == "Gauteng"
    assert out["rt3_brand"] == "Rawson Properties"


def test_carports_to_parking_spaces():
    out, _ = to_import_record(_by_ref(GAUTENG)["1400001"], province="Gauteng")
    assert out["parking_spaces"] == "2"
    assert out["garages"] == "3"


def test_branch_is_the_agency():
    out, _ = to_import_record(_by_ref(GAUTENG)["1289051"], province="Gauteng")
    assert out["agency_vendor_id"] == "1232"
    assert out["agency_name"] == "JHB Commercial"


def test_real_two_record_extract_maps_clean():
    records = parse(REAL.read_text())
    assert len(records) == 2
    out0, _ = to_import_record(records[0], province="Gauteng")
    assert out0["vendor_listing_id"] == "1289051"
    assert out0["features"] == []
    assert "rt3_agents" not in out0  # zero agents
    out1, _ = to_import_record(records[1], province="Gauteng")
    assert out1["vendor_listing_id"] == "1312993"
    assert out1["agent_vendor_id"] == "bertie.cilliers@rawson.co.za"
    assert "Garden" in out1["features"]
    assert "__validation_error__" not in out1
