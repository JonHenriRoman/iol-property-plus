"""Transactional diff-and-upsert of the desired geography into provinces/cities/suburbs.

One transaction wraps the whole file. Each level is diffed against what is already
in the table so the inserted / updated / unchanged counts are exact rather than
inferred. A mid-run failure rolls the whole file back.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from .geography import COUNTRY_CODE, DesiredGeography, NaturalKeyCollisionError

__all__ = ["LoadReport", "LevelCounts", "SchemaNotReadyError", "load"]

_REQUIRED_SUBURB_COLUMNS = {"extension", "external_id", "alternate_names"}


class SchemaNotReadyError(RuntimeError):
    """suburbs is missing the columns/constraints from db/migrations/001_*."""


@dataclass(frozen=True, slots=True)
class LevelCounts:
    before: int
    after: int
    inserted: int
    updated: int
    unchanged: int


@dataclass(frozen=True, slots=True)
class LoadReport:
    provinces: LevelCounts
    cities: LevelCounts
    suburbs: LevelCounts
    committed: bool


def _assert_schema_ready(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'suburbs'
        """
    )
    present = {r["column_name"] for r in cur.fetchall()}
    missing = _REQUIRED_SUBURB_COLUMNS - present
    if missing:
        raise SchemaNotReadyError(
            "suburbs is missing column(s): "
            + ", ".join(sorted(missing))
            + " — apply db/migrations/001_suburbs_property24_columns.sql in DataGrip "
            "and run `pnpm db:pull`, then retry."
        )

    cur.execute(
        """
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_suburbs_external_id' AND conrelid = 'public.suburbs'::regclass
        """
    )
    if cur.fetchone() is None:
        raise SchemaNotReadyError(
            "suburbs is missing constraint uq_suburbs_external_id — apply "
            "db/migrations/001_suburbs_property24_columns.sql in DataGrip, then retry."
        )


def _count(cur: psycopg.Cursor, table: str) -> int:
    cur.execute(f"SELECT count(*) AS n FROM {table}")
    return cur.fetchone()["n"]


def _sync_provinces(
    cur: psycopg.Cursor, desired: DesiredGeography
) -> tuple[LevelCounts, dict[str, int]]:
    before = _count(cur, "provinces")
    cur.execute(
        "SELECT id, name, code FROM provinces WHERE country_code = %s",
        (COUNTRY_CODE,),
    )
    existing = {r["name"]: r for r in cur.fetchall()}

    inserted = updated = unchanged = 0
    id_by_name: dict[str, int] = {}

    for prov in desired.provinces:
        current = existing.get(prov.name)
        if current is None:
            cur.execute(
                "INSERT INTO provinces (name, code, country_code) VALUES (%s, %s, %s) RETURNING id",
                (prov.name, prov.code, prov.country_code),
            )
            id_by_name[prov.name] = cur.fetchone()["id"]
            inserted += 1
        else:
            id_by_name[prov.name] = current["id"]
            if current["code"] != prov.code:
                cur.execute(
                    "UPDATE provinces SET code = %s WHERE id = %s",
                    (prov.code, current["id"]),
                )
                updated += 1
            else:
                unchanged += 1

    after = _count(cur, "provinces")
    return LevelCounts(before, after, inserted, updated, unchanged), id_by_name


def _sync_cities(
    cur: psycopg.Cursor, desired: DesiredGeography, province_id: dict[str, int]
) -> tuple[LevelCounts, dict[tuple[str, str], int]]:
    before = _count(cur, "cities")
    wanted_province_ids = tuple(sorted({province_id[c.province_name] for c in desired.cities}))
    existing: dict[tuple[int, str], dict] = {}
    if wanted_province_ids:
        cur.execute(
            "SELECT id, province_id, name, slug FROM cities WHERE province_id = ANY(%s)",
            (list(wanted_province_ids),),
        )
        existing = {(r["province_id"], r["name"]): r for r in cur.fetchall()}

    inserted = updated = unchanged = 0
    id_by_key: dict[tuple[str, str], int] = {}

    for city in desired.cities:
        pid = province_id[city.province_name]
        current = existing.get((pid, city.name))
        if current is None:
            cur.execute(
                "INSERT INTO cities (province_id, name, slug) VALUES (%s, %s, %s) RETURNING id",
                (pid, city.name, city.slug),
            )
            id_by_key[(city.province_name, city.name)] = cur.fetchone()["id"]
            inserted += 1
        else:
            id_by_key[(city.province_name, city.name)] = current["id"]
            if current["slug"] != city.slug:
                cur.execute(
                    "UPDATE cities SET slug = %s WHERE id = %s", (city.slug, current["id"])
                )
                updated += 1
            else:
                unchanged += 1

    after = _count(cur, "cities")
    return LevelCounts(before, after, inserted, updated, unchanged), id_by_key


_SUBURB_FIELDS = ("city_id", "name", "slug", "extension", "postal_code", "alternate_names")


def _sync_suburbs(
    cur: psycopg.Cursor,
    desired: DesiredGeography,
    city_id: dict[tuple[str, str], int],
) -> LevelCounts:
    before = _count(cur, "suburbs")

    cur.execute(
        """
        SELECT id, city_id, name, slug, extension, postal_code, alternate_names, external_id
        FROM suburbs
        WHERE external_id IS NOT NULL
        """
    )
    existing = {r["external_id"]: r for r in cur.fetchall()}

    # build_desired() has already guaranteed no two Ids share a natural key; the
    # UniqueViolation catch below is the database-level safety net.
    resolved: list[tuple[int, dict]] = []
    for sub in desired.suburbs:
        cid = city_id[(sub.province_name, sub.city_name)]
        resolved.append(
            (
                sub.external_id,
                {
                    "city_id": cid,
                    "name": sub.name,
                    "slug": sub.slug,
                    "extension": sub.extension,
                    "postal_code": sub.postal_code,
                    "alternate_names": sub.alternate_names,
                },
            )
        )

    inserted = updated = unchanged = 0
    to_insert: list[tuple] = []
    to_update: list[tuple] = []

    for external_id, target in resolved:
        current = existing.get(external_id)
        if current is None:
            to_insert.append(
                (
                    target["city_id"],
                    target["name"],
                    target["slug"],
                    target["extension"],
                    target["postal_code"],
                    target["alternate_names"],
                    external_id,
                )
            )
            inserted += 1
        elif any(current[f] != target[f] for f in _SUBURB_FIELDS):
            to_update.append(
                (
                    target["city_id"],
                    target["name"],
                    target["slug"],
                    target["extension"],
                    target["postal_code"],
                    target["alternate_names"],
                    external_id,
                )
            )
            updated += 1
        else:
            unchanged += 1

    try:
        if to_insert:
            cur.executemany(
                """
                INSERT INTO suburbs
                    (city_id, name, slug, extension, postal_code, alternate_names, external_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                to_insert,
            )
        if to_update:
            cur.executemany(
                """
                UPDATE suburbs SET
                    city_id = %s, name = %s, slug = %s, extension = %s,
                    postal_code = %s, alternate_names = %s
                WHERE external_id = %s
                """,
                to_update,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise NaturalKeyCollisionError(
            f"a suburb write violated a UNIQUE constraint: {exc}"
        ) from exc

    after = _count(cur, "suburbs")
    return LevelCounts(before, after, inserted, updated, unchanged)


def load(conn: psycopg.Connection, desired: DesiredGeography, *, dry_run: bool) -> LoadReport:
    report: dict[str, LevelCounts] = {}

    try:
        with conn.transaction() as tx:
            cur = conn.cursor(row_factory=dict_row)  # scoped to this call, not the connection
            _assert_schema_ready(cur)

            report["provinces"], province_id = _sync_provinces(cur, desired)
            report["cities"], city_id = _sync_cities(cur, desired, province_id)
            report["suburbs"] = _sync_suburbs(cur, desired, city_id)

            if dry_run:
                # Unwind the transaction without surfacing an error — nothing persists.
                raise psycopg.Rollback(tx)
    except psycopg.Rollback:
        pass

    return LoadReport(
        provinces=report["provinces"],
        cities=report["cities"],
        suburbs=report["suburbs"],
        committed=not dry_run,
    )
