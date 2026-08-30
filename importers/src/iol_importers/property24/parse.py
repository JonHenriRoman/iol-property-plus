"""Parse a saved Property24 CSV: verify the header, filter to South Africa first.

The country filter runs before any geography resolution or database work — a
non-South-African row is counted for visibility and then dropped here. It never
reaches the loader and is never written anywhere, staging included.
"""

from __future__ import annotations

import csv
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# The real column order, confirmed against a live download. Verified rather than
# assumed because the feed can change.
EXPECTED_HEADER = [
    "Country",
    "Province",
    "City",
    "Suburb",
    "Extension",
    "Postal Code",
    "Id",
    "Alternate Names",
]

TARGET_COUNTRY = "South Africa"


class HeaderMismatchError(RuntimeError):
    """The CSV header is not the 8 expected columns in the expected order."""


@dataclass(frozen=True, slots=True)
class SuburbRow:
    """One South African row from the feed, trimmed and normalised."""

    country: str
    province: str
    city: str
    suburb: str
    extension: str | None
    postal_code: str | None
    external_id: int
    alternate_names: str | None


@dataclass(frozen=True, slots=True)
class ParseResult:
    rows: list[SuburbRow]
    country_counts: Counter[str]

    @property
    def south_africa_count(self) -> int:
        return self.country_counts[TARGET_COUNTRY]

    @property
    def filtered_out(self) -> list[tuple[str, int]]:
        return sorted(
            ((c, n) for c, n in self.country_counts.items() if c != TARGET_COUNTRY),
            key=lambda pair: (-pair[1], pair[0]),
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _rows_from_reader(reader: Iterable[dict[str, str]]) -> Iterator[tuple[str, SuburbRow | None]]:
    """Yield (country, row-or-None). row is None for non-target countries."""
    for raw in reader:
        country = (raw.get("Country") or "").strip()
        if country != TARGET_COUNTRY:
            yield country or "(blank)", None
            continue

        raw_id = (raw.get("Id") or "").strip()
        if not raw_id:
            # A South African row with no Property24 Id has no upsert key.
            raise ValueError(f"South African row without an Id: {raw!r}")

        yield country, SuburbRow(
            country=country,
            province=(raw.get("Province") or "").strip(),
            city=(raw.get("City") or "").strip(),
            suburb=(raw.get("Suburb") or "").strip(),
            extension=_clean(raw.get("Extension")),
            postal_code=_clean(raw.get("Postal Code")),
            external_id=int(raw_id),
            alternate_names=_clean(raw.get("Alternate Names")),
        )


def parse_csv(path: Path) -> ParseResult:
    """Read the saved CSV, assert the header, return only South African rows."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise HeaderMismatchError("CSV is empty") from None

        if header != EXPECTED_HEADER:
            raise HeaderMismatchError(
                f"unexpected header\n  expected: {EXPECTED_HEADER}\n  actual:   {header}"
            )

        dict_reader = csv.DictReader(handle, fieldnames=EXPECTED_HEADER)

        counts: Counter[str] = Counter()
        kept: list[SuburbRow] = []
        for country, row in _rows_from_reader(dict_reader):
            counts[country] += 1
            if row is not None:
                kept.append(row)

    return ParseResult(rows=kept, country_counts=counts)
