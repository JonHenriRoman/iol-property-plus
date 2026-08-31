"""Offline — integrity of the transcribed Appendix A crosswalk."""

from __future__ import annotations

from iol_importers.propertyengine.locations import (
    LOCATIONS,
    SA_LAT_RANGE,
    SA_LON_RANGE,
    lookup,
)

# The nine SA provinces (matches iol_importers.property24.geography.PROVINCE_CODES).
_SA_PROVINCES = {
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "North West",
    "Northern Cape",
    "Western Cape",
}


def test_crosswalk_is_substantial():
    # Appendix A is ~500 rows across 17 table pages
    assert len(LOCATIONS) > 480


def test_every_location_id_is_unique_and_numeric():
    for key, loc in LOCATIONS.items():
        assert key == loc.location_id
        assert isinstance(loc.location_id, int)


def test_every_province_is_a_real_sa_province():
    provinces = {loc.province for loc in LOCATIONS.values()}
    assert provinces == _SA_PROVINCES


def test_every_coordinate_is_inside_the_sa_bounding_box():
    for loc in LOCATIONS.values():
        assert SA_LAT_RANGE[0] <= loc.latitude <= SA_LAT_RANGE[1], loc
        assert SA_LON_RANGE[0] <= loc.longitude <= SA_LON_RANGE[1], loc


def test_lookup_accepts_number_and_string_and_rejects_junk():
    assert lookup(3100047).locality == "Rondebosch"
    assert lookup("3100047").locality == "Rondebosch"
    assert lookup(" 3100108 ").locality == "Sandton"
    assert lookup(None) is None
    assert lookup("not-a-number") is None
    assert lookup(999999999) is None


def test_metro_suburbs_and_towns_both_present():
    # a genuine metro suburb
    assert lookup(3100335).locality == "Bryanston"
    assert lookup(3100335).area == "Johannesburg"
    # a town where the "locality" is really a city
    assert lookup(3100306).locality == "Port Elizabeth"
    assert lookup(3100306).area is None
