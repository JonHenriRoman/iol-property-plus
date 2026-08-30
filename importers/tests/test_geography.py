import pytest

from iol_importers.property24.geography import (
    PROVINCE_CODES,
    NaturalKeyCollisionError,
    UnknownProvinceError,
    build_desired,
)
from iol_importers.property24.parse import SuburbRow, parse_csv


def _row(province, city, suburb, ext=None, ext_id=1):
    return SuburbRow(
        country="South Africa",
        province=province,
        city=city,
        suburb=suburb,
        extension=ext,
        postal_code=None,
        external_id=ext_id,
        alternate_names=None,
    )


def test_all_nine_provinces_have_codes():
    assert set(PROVINCE_CODES) == {
        "Eastern Cape",
        "Free State",
        "Gauteng",
        "KwaZulu Natal",
        "Limpopo",
        "Mpumalanga",
        "North West",
        "Northern Cape",
        "Western Cape",
    }


def test_build_desired_from_sample(sample_csv):
    result = parse_csv(sample_csv)
    desired = build_desired(result.rows)

    assert {p.name for p in desired.provinces} == {
        "Western Cape",
        "Gauteng",
        "KwaZulu Natal",
        "Eastern Cape",
        "Free State",
    }
    assert {(p.name, p.code) for p in desired.provinces} >= {("Western Cape", "WC")}
    assert all(p.country_code == "ZA" for p in desired.provinces)

    assert len(desired.cities) == 5
    assert len(desired.suburbs) == 6


def test_suburb_slug_folds_extension():
    desired = build_desired([_row("Eastern Cape", "Aberdeen", "Aberdeen", "Lotusville", 5)])
    assert desired.suburbs[0].slug == "aberdeen-lotusville"


def test_two_extensions_of_one_name_are_distinct_suburbs():
    desired = build_desired(
        [
            _row("Western Cape", "Cape Town", "Claremont", None, 1),
            _row("Western Cape", "Cape Town", "Claremont", "Upper", 2),
        ]
    )
    assert len(desired.suburbs) == 2
    assert len(desired.cities) == 1
    slugs = {s.slug for s in desired.suburbs}
    assert slugs == {"claremont", "claremont-upper"}


def test_unknown_province_is_fatal():
    rows = [_row("Atlantis", "Nowhere", "Nowhere", None, 9)]
    with pytest.raises(UnknownProvinceError):
        build_desired(rows)


def test_two_ids_sharing_a_natural_key_is_fatal():
    rows = [
        _row("Gauteng", "Johannesburg", "Sandton", None, 10),
        _row("Gauteng", "Johannesburg", "Sandton", None, 11),
    ]
    with pytest.raises(NaturalKeyCollisionError):
        build_desired(rows)
