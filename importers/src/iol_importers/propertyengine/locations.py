"""The Gumtree Pro Appendix A location gazetteer, as a checked-in crosswalk.

Appendix A of the schema doc (pages 12-28, image-only tables) maps a numeric
``LocationID`` to a ``SA -> Province -> [Area ->] Locality`` path plus a
lat/long centroid. It is **not** suburb-level in general — most rows are a city
or town ("Port Elizabeth", "Rustenburg"); some, in the metros, are a genuine
suburb ("Bryanston", "Rondebosch"). It has no link to our own ``suburbs`` id
space, which is Property24-derived.

``locations.csv`` beside this module is the reviewable artefact — one row per
``LocationID``, transcribed from the rendered PDF pages during the build and
verified (unique ids, known SA provinces, coordinates inside the SA bounding
box). This module just loads it.

Runtime use (see ``map.py``): when a ``Property`` carries a ``Location``, we take
its province + area into ``raw_data`` and its centroid as a coordinate fallback,
and pass the *locality* name as the suburb candidate — which resolves for the
metro suburb rows and lands ``suburb_id`` NULL (listing still imports) for the
city rows. A ``Location`` id absent from this table is a per-run warning, not a
record rejection: a stale gazetteer is our problem, not the vendor's.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

_CSV_PATH = Path(__file__).with_name("locations.csv")

# SA bounding box — used by the build-time verification and re-exported for tests.
SA_LAT_RANGE = (-35.0, -22.0)
SA_LON_RANGE = (16.0, 33.5)


@dataclass(frozen=True, slots=True)
class Location:
    location_id: int
    province: str
    area: str | None
    locality: str
    latitude: float
    longitude: float


def _load() -> dict[int, Location]:
    out: dict[int, Location] = {}
    with _CSV_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            loc = Location(
                location_id=int(row["location_id"]),
                province=row["province"].strip(),
                area=row["area"].strip() or None,
                locality=row["locality"].strip(),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            )
            out[loc.location_id] = loc
    return out


LOCATIONS: dict[int, Location] = _load()


def lookup(location_id: object) -> Location | None:
    """Resolve a feed ``Location`` value (number or numeric string) to a
    :class:`Location`, or ``None`` when it is not in the gazetteer / not numeric."""
    if location_id is None:
        return None
    try:
        key = int(str(location_id).strip())
    except (TypeError, ValueError):
        return None
    return LOCATIONS.get(key)
