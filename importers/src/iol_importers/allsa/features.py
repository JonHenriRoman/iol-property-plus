"""Parse an AllSA ``<Features>`` bag.

``<Features>`` is free-form: the child set varies per listing and the observed
feed carries 28 distinct tags (``Bedrooms Bathrooms Kitchen Built-in_Cupboards
Lounges Dining_Areas Garages En_Suite Study Guest_Toilet Erf_Size Floor_Size
Rates Garden Levies Carports Alarm Land_Size Swimming_Pool Storeroom Flatlet
Pets_Allowed Laundry Borehole Parking Staff_Quarters Available Toilet``) — and
that list is illustrative, not exhaustive.

So the parser **iterates the element's actual children** against a registry:

* known tags map to typed columns (``bedrooms`` …) or to a human label in
  ``listings.features`` or to ``raw_data.allsa_features``;
* an unknown tag is never an error — its raw value goes to
  ``raw_data.allsa_features_extra``, a ``Yes`` value also becomes a label, and the
  tag is tallied so a new vendor feature shows up in the run output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

_HECTARE_TO_SQM = Decimal(10000)
# listings.erf_size_sqm / floor_size_sqm are numeric(10,2).
_MAX_SQM = Decimal("99999999.99")
# Land_Size is free text and its unit is inconsistent in the real feed: most
# values are hectares ("1", "4.28", "8.5") but some are already square metres
# ("10712" for a listing whose description says "1.0712HA"). Treat a value at or
# above this as already-m², below it as hectares.
_LAND_SQM_THRESHOLD = Decimal(1000)

# kind -> handling. Tag keys are normalised: lower-cased, '-' -> '_'.
_COUNT_COLUMN = {"bedrooms": "bedrooms", "bathrooms": "bathrooms", "garages": "garages"}
_COUNT_PARKING = frozenset({"carports", "parking"})
_COUNT_LABEL = frozenset({"lounges", "dining_areas", "en_suite"})
_AREA_SQM = {"erf_size": "erf_size", "floor_size": "floor_size"}
_MONEY = {"rates": "rates_and_taxes", "levies": "levies"}
_FLAG = frozenset(
    {
        "kitchen",
        "study",
        "guest_toilet",
        "toilet",
        "garden",
        "alarm",
        "swimming_pool",
        "storeroom",
        "flatlet",
        "laundry",
        "borehole",
        "staff_quarters",
        "built_in_cupboards",
        "pets_allowed",
    }
)
_DATE = {"available": "allsa_available_from"}
_LAND_HA = "land_size"

_YES = frozenset({"yes", "true", "y", "1"})


@dataclass
class ParsedFeatures:
    columns: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)
    raw_dates: dict[str, str] = field(default_factory=dict)
    unknown_tags: list[str] = field(default_factory=list)


def _norm(tag: str) -> str:
    return tag.strip().lower().replace("-", "_")


def _label(tag: str) -> str:
    return tag.replace("_", " ").replace("-", " ").strip()


def _int(value: str) -> int | None:
    try:
        return int(Decimal(value.replace(",", ".")))
    except (InvalidOperation, ValueError):
        return None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:
        return None


def _land_size_sqm(value: str) -> Decimal | None:
    """Land_Size -> square metres, applying the hectares-vs-m² heuristic."""
    n = _decimal(value)
    if n is None or n <= 0:
        return None
    return n if n >= _LAND_SQM_THRESHOLD else n * _HECTARE_TO_SQM


def parse_features(features: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> ParsedFeatures:
    """Deduped ``(tag, value)`` pairs -> :class:`ParsedFeatures`."""
    out = ParsedFeatures()
    parking = 0
    parking_seen = False
    land_sqm: Decimal | None = None

    for raw_tag, raw_value in features:
        value = (raw_value or "").strip()
        key = _norm(raw_tag)

        if key in _COUNT_COLUMN:
            if value:
                out.columns[_COUNT_COLUMN[key]] = value
        elif key in _COUNT_PARKING:
            n = _int(value)
            if n is not None:
                parking += n
                parking_seen = True
        elif key in _COUNT_LABEL:
            n = _int(value)
            if n:
                out.labels.append(f"{n} {_label(raw_tag)}")
        elif key in _AREA_SQM:
            _set_area(out, _AREA_SQM[key], raw_tag, value)
        elif key == _LAND_HA:
            land_sqm = _land_size_sqm(value)
            if value:
                out.extra[raw_tag] = value
        elif key in _MONEY:
            if value:
                out.columns[_MONEY[key]] = value
        elif key in _FLAG:
            if value.lower() in _YES:
                out.labels.append(_label(raw_tag))
        elif key in _DATE:
            if value:
                out.raw_dates[_DATE[key]] = value
        else:
            out.unknown_tags.append(raw_tag)
            if value:
                out.extra[raw_tag] = value
            if value.lower() in _YES:
                out.labels.append(_label(raw_tag))

    if parking_seen:
        out.columns["parking_spaces"] = str(parking)

    # Land_Size backfills erf_size only when Erf_Size was absent and it fits.
    if land_sqm is not None and "erf_size" not in out.columns and land_sqm <= _MAX_SQM:
        out.columns["erf_size"] = str(land_sqm)

    return out


def _set_area(out: ParsedFeatures, column: str, raw_tag: str, value: str) -> None:
    """Promote Erf_Size / Floor_Size to its column, or keep the raw value in
    ``extra`` when it is blank, unparseable, or overflows numeric(10,2)."""
    if not value:
        return
    n = _decimal(value)
    if n is not None and 0 <= n <= _MAX_SQM:
        out.columns[column] = value
    else:
        out.extra[raw_tag] = value
