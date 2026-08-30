"""Pure normalisation of vendor field values — no database, no I/O.

``listing_type`` normalisation happens here, in the importer, so queries never
have to cope with 'For Sale' / '4 Sale' / 'FORSALE' variants at read time.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

ListingType = Literal["Sale", "Rental", "Unknown"]

_ALNUM = re.compile(r"[^a-z0-9]+")

# Keyed on the value after casefold + stripping every non-alphanumeric character.
# Add a vendor variant by adding one entry.
_SALE_TOKENS: frozenset[str] = frozenset(
    {"sale", "forsale", "4sale", "tosell", "resale", "sales", "buy", "forpurchase"}
)
_RENTAL_TOKENS: frozenset[str] = frozenset(
    {"rental", "rentals", "rent", "forrent", "4rent", "tolet", "let", "torent", "letting", "lease"}
)


class RecordParseError(ValueError):
    """A field is present but structurally unparseable — routes to error_type='parse'."""


def _key(raw: str) -> str:
    return _ALNUM.sub("", raw.casefold())


def normalize_listing_type(raw: object) -> ListingType:
    """Map a vendor listing-type value onto the ('Sale', 'Rental', 'Unknown') enum."""
    if raw is None:
        return "Unknown"
    token = _key(str(raw))
    if not token:
        return "Unknown"
    if token in _SALE_TOKENS:
        return "Sale"
    if token in _RENTAL_TOKENS:
        return "Rental"
    return "Unknown"


def clean_str(raw: object) -> str | None:
    """Trim to a non-empty string, or None."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def to_decimal(raw: object, *, field: str) -> Decimal | None:
    """Parse a money / measurement value. Blank -> None. Junk -> RecordParseError."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip()
    if not text:
        return None
    # tolerate thousands separators, currency prefixes, a trailing m²/sqm
    cleaned = re.sub(r"(?i)[r$€£\s,]|m²|sqm|m2", "", text)
    if cleaned in {"", "-", "."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise RecordParseError(f"{field}: cannot parse {raw!r} as a number") from exc


def to_int(raw: object, *, field: str) -> int | None:
    """Parse an integer count. Blank -> None. Junk -> RecordParseError."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise RecordParseError(f"{field}: expected a number, got a boolean")
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        # accept "3", "3.0", "3,0"
        return int(Decimal(text.replace(",", ".")))
    except (InvalidOperation, ValueError) as exc:
        raise RecordParseError(f"{field}: cannot parse {raw!r} as an integer") from exc


_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_FALSE = frozenset({"false", "f", "no", "n", "0"})


def to_bool(raw: object, *, field: str) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().casefold()
    if not text:
        return None
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise RecordParseError(f"{field}: cannot parse {raw!r} as a boolean")


def to_str_list(raw: object) -> list[str]:
    """Vendor 'features' -> a clean list. Accepts a list or a delimited string."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        items = [part.strip() for part in re.split(r"[|,;]", str(raw))]
    return [item for item in items if item]


def split_person_name(full: object) -> tuple[str, str]:
    """('Jane Q Smith') -> ('Jane Q', 'Smith'). A single token -> ('', token).

    agents.first_name / last_name are both NOT NULL, so first_name may be '' but
    is never None.
    """
    text = clean_str(full) or ""
    parts = text.split()
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return ("", parts[0])
    return (" ".join(parts[:-1]), parts[-1])
