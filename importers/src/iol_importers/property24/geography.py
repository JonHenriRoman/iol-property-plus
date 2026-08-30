"""Turn parsed South African rows into the desired province / city / suburb sets.

The feed has no province code and no slugs; those NOT NULL columns are derived
here. The feed has no latitude/longitude at all, so those columns are never set.
"""

from __future__ import annotations

from dataclasses import dataclass

from iol_importers.slugify import slugify

from .parse import SuburbRow

COUNTRY_CODE = "ZA"

# Fixed 9-entry map. An unrecognised province name fails the run rather than
# inventing a code. Keys match the feed's spelling ("KwaZulu Natal", no hyphen).
PROVINCE_CODES: dict[str, str] = {
    "Eastern Cape": "EC",
    "Free State": "FS",
    "Gauteng": "GP",
    "KwaZulu Natal": "KZN",
    "Limpopo": "LP",
    "Mpumalanga": "MP",
    "North West": "NW",
    "Northern Cape": "NC",
    "Western Cape": "WC",
}


class UnknownProvinceError(RuntimeError):
    """A row names a province that is not one of the nine South African provinces."""


class NaturalKeyCollisionError(RuntimeError):
    """Two distinct Property24 Ids resolve to the same suburb natural key."""


@dataclass(frozen=True, slots=True)
class DesiredProvince:
    name: str
    code: str
    country_code: str = COUNTRY_CODE


@dataclass(frozen=True, slots=True)
class DesiredCity:
    province_name: str
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class DesiredSuburb:
    province_name: str
    city_name: str
    name: str
    slug: str
    extension: str | None
    postal_code: str | None
    external_id: int
    alternate_names: str | None


@dataclass(frozen=True, slots=True)
class DesiredGeography:
    provinces: list[DesiredProvince]
    cities: list[DesiredCity]
    suburbs: list[DesiredSuburb]


def _suburb_slug(name: str, extension: str | None) -> str:
    return slugify(f"{name} {extension}" if extension else name)


def build_desired(rows: list[SuburbRow]) -> DesiredGeography:
    unknown = sorted({r.province for r in rows if r.province not in PROVINCE_CODES})
    if unknown:
        raise UnknownProvinceError(
            "unrecognised province name(s) in the feed: " + ", ".join(repr(u) for u in unknown)
        )

    provinces = [
        DesiredProvince(name=name, code=PROVINCE_CODES[name])
        for name in sorted({r.province for r in rows})
    ]

    cities_seen: dict[tuple[str, str], DesiredCity] = {}
    for r in rows:
        key = (r.province, r.city)
        if key not in cities_seen:
            cities_seen[key] = DesiredCity(
                province_name=r.province,
                name=r.city,
                slug=slugify(r.city),
            )
    cities = sorted(cities_seen.values(), key=lambda c: (c.province_name, c.name))

    suburbs = [
        DesiredSuburb(
            province_name=r.province,
            city_name=r.city,
            name=r.suburb,
            slug=_suburb_slug(r.suburb, r.extension),
            extension=r.extension,
            postal_code=r.postal_code,
            external_id=r.external_id,
            alternate_names=r.alternate_names,
        )
        for r in rows
    ]
    suburbs.sort(key=lambda s: s.external_id)
    _guard_natural_keys(suburbs)

    return DesiredGeography(provinces=provinces, cities=cities, suburbs=suburbs)


def _guard_natural_keys(suburbs: list[DesiredSuburb]) -> None:
    """Fail if two different Property24 Ids share a suburb's (city, name, extension)
    or (city, slug) — the UNIQUE constraints on the table. City is keyed by
    (province, city) name here, which is 1:1 with city_id within one import."""
    by_name_ext: dict[tuple[str, str, str, str | None], int] = {}
    by_slug: dict[tuple[str, str, str], int] = {}
    for s in suburbs:
        ne_key = (s.province_name, s.city_name, s.name, s.extension)
        prior = by_name_ext.get(ne_key)
        if prior is not None and prior != s.external_id:
            raise NaturalKeyCollisionError(
                f"Property24 Ids {prior} and {s.external_id} share "
                f"({s.province_name} / {s.city_name} / name={s.name!r}, extension={s.extension!r})"
            )
        by_name_ext[ne_key] = s.external_id

        slug_key = (s.province_name, s.city_name, s.slug)
        prior_slug = by_slug.get(slug_key)
        if prior_slug is not None and prior_slug != s.external_id:
            raise NaturalKeyCollisionError(
                f"Property24 Ids {prior_slug} and {s.external_id} share "
                f"({s.province_name} / {s.city_name} / slug={s.slug!r})"
            )
        by_slug[slug_key] = s.external_id
