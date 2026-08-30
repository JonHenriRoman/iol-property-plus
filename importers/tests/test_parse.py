import csv

import pytest

from iol_importers.property24.parse import (
    EXPECTED_HEADER,
    HeaderMismatchError,
    parse_csv,
)


def test_confirmed_header_matches_documented_order():
    assert EXPECTED_HEADER == [
        "Country",
        "Province",
        "City",
        "Suburb",
        "Extension",
        "Postal Code",
        "Id",
        "Alternate Names",
    ]


def test_filters_to_south_africa_only(sample_csv):
    result = parse_csv(sample_csv)
    assert {r.country for r in result.rows} == {"South Africa"}
    assert result.south_africa_count == 6
    assert len(result.rows) == 6


def test_reports_per_country_filtered_counts(sample_csv):
    result = parse_csv(sample_csv)
    assert result.filtered_out == [
        ("Nigeria", 2),
        ("Kenya", 1),
        ("Republic Of Mauritius", 1),
        ("Swaziland", 1),
        ("Zimbabwe", 1),
    ]
    # Kenya is counted for visibility but never retained.
    assert result.country_counts["Kenya"] == 1
    assert all(r.country == "South Africa" for r in result.rows)


def test_blank_postal_code_becomes_none(sample_csv):
    result = parse_csv(sample_csv)
    by_id = {r.external_id: r for r in result.rows}
    assert by_id[1006].postal_code is None
    assert by_id[1001].postal_code == "7708"


def test_blank_extension_and_alternate_names_become_none(sample_csv):
    result = parse_csv(sample_csv)
    by_id = {r.external_id: r for r in result.rows}
    assert by_id[1001].extension is None
    assert by_id[1002].extension == "Upper"
    assert by_id[1001].alternate_names is None
    assert by_id[1003].alternate_names == "Sandton CBD"


def test_id_is_parsed_as_int(sample_csv):
    result = parse_csv(sample_csv)
    assert all(isinstance(r.external_id, int) for r in result.rows)


def test_header_mismatch_is_fatal(tmp_path):
    bad = tmp_path / "bad.csv"
    with bad.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Country", "Province", "City", "Suburb"])  # wrong shape
        w.writerow(["South Africa", "Gauteng", "Johannesburg", "Sandton"])
    with pytest.raises(HeaderMismatchError):
        parse_csv(bad)


def test_south_african_row_without_id_is_fatal(tmp_path):
    bad = tmp_path / "noid.csv"
    with bad.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(EXPECTED_HEADER)
        w.writerow(["South Africa", "Gauteng", "Johannesburg", "Sandton", "", "2196", "", ""])
    with pytest.raises(ValueError):
        parse_csv(bad)
