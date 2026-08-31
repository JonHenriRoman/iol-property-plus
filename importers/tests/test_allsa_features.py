"""AllSA <Features> registry — varying child sets, unknown tags, unit conversion."""

from __future__ import annotations

from decimal import Decimal

from iol_importers.allsa.features import parse_features


def _pf(*pairs):
    return parse_features(list(pairs))


def test_apartment_floor_size_beds_baths():
    p = _pf(("Floor_Size", "48"), ("Bedrooms", "2"), ("Bathrooms", "2"))
    assert p.columns == {"floor_size": "48", "bedrooms": "2", "bathrooms": "2"}
    assert p.labels == []


def test_farm_land_size_only_backfills_erf_in_sqm():
    p = _pf(("Land_Size", "4.28"), ("Borehole", "Yes"))
    assert Decimal(p.columns["erf_size"]) == Decimal("42800.00")
    assert "Borehole" in p.labels
    assert p.extra == {"Land_Size": "4.28"}


def test_land_size_large_value_is_treated_as_already_sqm():
    # real feed: <Land_Size>10712</Land_Size> for a listing described as "1.0712HA"
    p = _pf(("Land_Size", "10712"))
    assert p.columns["erf_size"] == "10712"


def test_land_size_overflowing_the_column_is_dropped_not_promoted():
    p = _pf(("Land_Size", "200000000"))  # 2e8 m2 > numeric(10,2) max
    assert "erf_size" not in p.columns
    assert p.extra == {"Land_Size": "200000000"}


def test_erf_size_overflow_kept_in_extra():
    p = _pf(("Erf_Size", "123456789"))
    assert "erf_size" not in p.columns
    assert p.extra == {"Erf_Size": "123456789"}


def test_erf_size_wins_over_land_size():
    p = _pf(("Erf_Size", "300"), ("Land_Size", "1"))
    assert p.columns["erf_size"] == "300"
    assert p.extra == {"Land_Size": "1"}


def test_carports_plus_parking_sum_into_parking_spaces():
    p = _pf(("Carports", "2"), ("Parking", "1"))
    assert p.columns["parking_spaces"] == "3"


def test_count_labels_for_non_column_counts():
    p = _pf(("Lounges", "2"), ("Dining_Areas", "1"), ("En_Suite", "1"))
    assert p.labels == ["2 Lounges", "1 Dining Areas", "1 En Suite"]


def test_pets_allowed_zero_produces_no_label():
    p = _pf(("Pets_Allowed", "0"))
    assert p.labels == []


def test_flag_yes_becomes_label():
    p = _pf(("Swimming_Pool", "Yes"), ("Built-in_Cupboards", "Yes"))
    assert p.labels == ["Swimming Pool", "Built in Cupboards"]


def test_money_fields():
    p = _pf(("Rates", "662"), ("Levies", "880"))
    assert p.columns == {"rates_and_taxes": "662", "levies": "880"}


def test_available_date_goes_to_raw_dates():
    p = _pf(("Available", "2026/08/14 00:00:00"))
    assert p.raw_dates == {"allsa_available_from": "2026/08/14 00:00:00"}


def test_unknown_tag_is_kept_not_dropped():
    p = _pf(("Solar_Geyser", "Yes"), ("Roof_Type", "Tile"))
    assert set(p.unknown_tags) == {"Solar_Geyser", "Roof_Type"}
    assert p.extra == {"Solar_Geyser": "Yes", "Roof_Type": "Tile"}
    assert "Solar Geyser" in p.labels
    assert "Roof Type" not in p.labels
