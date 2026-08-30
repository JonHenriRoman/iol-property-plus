"""Offline tests for listing-record normalisation — no database."""

from __future__ import annotations

from decimal import Decimal

import pytest

from iol_importers.listings.normalize import (
    RecordParseError,
    normalize_listing_type,
    split_person_name,
    to_decimal,
    to_int,
    to_str_list,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sale", "Sale"),
        ("For Sale", "Sale"),
        ("4 Sale", "Sale"),
        ("FORSALE", "Sale"),
        ("to sell", "Sale"),
        ("Rental", "Rental"),
        ("For Rent", "Rental"),
        ("4 Rent", "Rental"),
        ("To Let", "Rental"),
        ("  to-let ", "Rental"),
        ("holiday swap", "Unknown"),
        ("", "Unknown"),
        (None, "Unknown"),
    ],
)
def test_normalize_listing_type(raw: object, expected: str):
    assert normalize_listing_type(raw) == expected


def test_to_decimal_tolerates_formatting():
    assert to_decimal("R 2,500,000", field="price") == Decimal("2500000")
    assert to_decimal("125.5 m²", field="floor_size") == Decimal("125.5")
    assert to_decimal("", field="price") is None
    assert to_decimal(None, field="price") is None


def test_to_decimal_rejects_junk():
    with pytest.raises(RecordParseError, match="price"):
        to_decimal("cheap", field="price")


def test_to_int_rejects_junk():
    assert to_int("3", field="bedrooms") == 3
    assert to_int("", field="bedrooms") is None
    with pytest.raises(RecordParseError, match="bedrooms"):
        to_int("lots", field="bedrooms")


def test_to_str_list_accepts_list_or_delimited_string():
    assert to_str_list(["Pool", " Solar "]) == ["Pool", "Solar"]
    assert to_str_list("Pool | Solar, Fibre") == ["Pool", "Solar", "Fibre"]
    assert to_str_list(None) == []


@pytest.mark.parametrize(
    ("full", "expected"),
    [
        ("Jane Smith", ("Jane", "Smith")),
        ("Jane Q Smith", ("Jane Q", "Smith")),
        ("Cher", ("", "Cher")),
        ("", ("", "")),
    ],
)
def test_split_person_name(full: str, expected: tuple[str, str]):
    assert split_person_name(full) == expected
