"""The Fusion AreaTree, flattened to a ``suburbId -> {suburb, city, province}`` crosswalk.

Fusion listings and developments carry only ``Address/@suburbId``. The AreaTree
events carry the ``Country -> Province -> City -> Suburb`` hierarchy with names.
This module turns those events into a flat lookup, persisted to
``data/fusion/area_tree.json``, that the listing mapper uses to hand the suburb
**name** to the existing ``resolve_suburb`` (name / alternate-name match against
our own ``provinces`` / ``cities`` / ``suburbs`` — no parallel geography table).
An unresolved suburb still imports the listing with ``suburb_id`` NULL.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

logger = logging.getLogger("iol_importers.fusion")


class AreaTree:
    def __init__(self, mapping: dict[str, dict[str, str]] | None = None) -> None:
        self._map: dict[str, dict[str, str]] = dict(mapping or {})

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, suburb_id: object) -> bool:
        return str(suburb_id) in self._map

    def entry(self, suburb_id: object) -> dict[str, str] | None:
        return self._map.get(str(suburb_id))

    def suburb_name(self, suburb_id: object) -> str | None:
        entry = self._map.get(str(suburb_id))
        return entry.get("suburb") if entry else None

    def apply_element(self, area_tree: Element) -> int:
        """Merge one ``<AreaTree>`` element. Returns the number of suburb nodes seen."""
        seen = 0
        for country in area_tree.iter("Country"):
            country_name = country.get("name") or country.get("countryId") or ""
            for province in country.iter("Province"):
                province_name = province.get("name") or province.get("provinceId") or ""
                for city in province.iter("City"):
                    city_name = city.get("name") or ""
                    for suburb in city.iter("Suburb"):
                        sid = suburb.get("suburbId")
                        name = suburb.get("name")
                        if not sid or not name:
                            continue
                        seen += 1
                        existing = self._map.get(sid)
                        if existing and existing.get("suburb") not in (None, name):
                            logger.warning(
                                "fusion: suburbId %s reused (%r -> %r)",
                                sid,
                                existing.get("suburb"),
                                name,
                            )
                        self._map[sid] = {
                            "suburb": name,
                            "city": city_name,
                            "province": province_name,
                            "country": country_name,
                        }
        return seen

    def remove(self, ref_tag: str, ref_id: str | None) -> bool:
        if ref_tag == "SuburbRef" and ref_id in self._map:
            del self._map[ref_id]
            return True
        if ref_tag in ("CityRef", "ProvinceRef"):
            logger.info("fusion: AreaTree %s delete not applied to the flat crosswalk", ref_tag)
        return False

    # -- persistence ------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> AreaTree:
        p = Path(path)
        if not p.is_file():
            return cls()
        try:
            data: Any = json.loads(p.read_text())
        except (ValueError, OSError):
            return cls()
        return cls(data if isinstance(data, dict) else None)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._map, sort_keys=True, indent=0))
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
