"""Parse a Webbox ``<features>`` bag and convert Webbox size units.

``<features>`` is free-form — the child set varies per listing (``bedrooms``,
``bathrooms``, ``garages``, ``taxes`` observed). Known tags route to typed
columns; an unknown tag is never an error — its value goes to
``raw_data.webbox_feature_<tag>``, a ``Yes`` value also becomes a feature label,
and the tag is tallied so a new vendor feature shows up in the run output.

``size_to_sqm`` converts ``land-size`` / ``property-size`` using Webbox's own
lowercase snake_case unit strings (``meters_squared``, ``hectares``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# listings.erf_size_sqm / floor_size_sqm are numeric(10,2).
_MAX_SQM = Decimal("99999999.99")

_UNIT_FACTOR: dict[str, Decimal] = {
    "meters_squared": Decimal(1),
    "meterssquared": Decimal(1),
    "m2": Decimal(1),
    "sqm": Decimal(1),
    "sq_m": Decimal(1),
    "square_meters": Decimal(1),
    "hectare": Decimal(10000),
    "hectares": Decimal(10000),
    "ha": Decimal(10000),
    "acre": Decimal("4046.8564224"),
    "acres": Decimal("4046.8564224"),
    "ac": Decimal("4046.8564224"),
}

# features tag (normalised: lower, '-' -> '_') -> typed record key
_COLUMN = {
    "bedrooms": "bedrooms",
    "bathrooms": "bathrooms",
    "garages": "garages",
    "taxes": "rates_and_taxes",
}
_YES = frozenset({"yes", "true", "y", "1", "t"})


@dataclass
class ParsedFeatures:
    columns: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)
    unknown_tags: list[str] = field(default_factory=list)


def _norm(tag: str) -> str:
    return tag.strip().lower().replace("-", "_")


def _label(tag: str) -> str:
    return tag.replace("_", " ").replace("-", " ").strip()


def parse_features(features: tuple[tuple[str, str], ...] | list[tuple[str, str]]) -> ParsedFeatures:
    """Ordered ``(tag, value)`` pairs -> :class:`ParsedFeatures`."""
    out = ParsedFeatures()
    for raw_tag, raw_value in features:
        value = (raw_value or "").strip()
        key = _norm(raw_tag)
        if key in _COLUMN:
            if value:
                out.columns[_COLUMN[key]] = value
        else:
            out.unknown_tags.append(raw_tag)
            if value:
                out.extra[raw_tag] = value
            if value.lower() in _YES:
                out.labels.append(_label(raw_tag))
    return out


def size_to_sqm(value: str | None, unit: str | None) -> str | None:
    """Webbox ``{…-value}`` + ``{…-unit}`` -> square-metre string, or None.

    An unknown or missing unit is treated as ``meters_squared``. A value that
    overflows ``numeric(10,2)`` after conversion returns None (kept in raw_data by
    the caller instead)."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        n = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None
    if n <= 0:
        return None
    factor = _UNIT_FACTOR.get(_norm(unit or ""), Decimal(1))
    sqm = (n * factor).quantize(Decimal("0.01"))
    if sqm > _MAX_SQM:
        return None
    return format(sqm.normalize(), "f")
