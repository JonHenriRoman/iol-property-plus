"""Opt-in database test. Skipped unless TEST_DATABASE_URL is set, and it never
touches the live iol_property_plus database on its own.

Everything runs inside one outer transaction that is rolled back at the end, so
the target database is left exactly as it was found — the test creates its own
provinces/cities/suburbs tables (post-migration shape) and drops them on rollback.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import psycopg
import pytest

from iol_importers.property24.geography import build_desired
from iol_importers.property24.load import load
from iol_importers.property24.parse import parse_csv

pytestmark = pytest.mark.dbtest

_SCHEMA_DDL = """
CREATE TABLE provinces (
    id serial PRIMARY KEY,
    name text NOT NULL,
    code text NOT NULL,
    country_code char(2) NOT NULL DEFAULT 'ZA',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_provinces_name UNIQUE (country_code, name),
    CONSTRAINT uq_provinces_code UNIQUE (country_code, code)
);
CREATE TABLE cities (
    id serial PRIMARY KEY,
    province_id int NOT NULL REFERENCES provinces(id) ON DELETE RESTRICT,
    name text NOT NULL,
    slug text NOT NULL,
    latitude numeric(9,6),
    longitude numeric(9,6),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_cities_province_name UNIQUE (province_id, name),
    CONSTRAINT uq_cities_province_slug UNIQUE (province_id, slug)
);
CREATE TABLE suburbs (
    id serial PRIMARY KEY,
    city_id int NOT NULL REFERENCES cities(id) ON DELETE RESTRICT,
    name text NOT NULL,
    slug text NOT NULL,
    postal_code text,
    latitude numeric(9,6),
    longitude numeric(9,6),
    is_active boolean NOT NULL DEFAULT true,
    extension varchar(100),
    external_id integer,
    alternate_names text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_suburbs_city_name_extension
        UNIQUE NULLS NOT DISTINCT (city_id, name, extension),
    CONSTRAINT uq_suburbs_city_slug UNIQUE (city_id, slug),
    CONSTRAINT uq_suburbs_external_id UNIQUE (external_id)
);
"""


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url) as connection:
        # One outer transaction; rolled back unconditionally so the test tables
        # never persist and the target database is left exactly as found.
        try:
            with connection.transaction() as tx:
                connection.execute(_SCHEMA_DDL)
                yield connection
                raise psycopg.Rollback(tx)
        except psycopg.Rollback:
            pass


@pytest.fixture
def desired(sample_csv):
    return build_desired(parse_csv(sample_csv).rows)


def test_first_load_inserts_everything(conn, desired):
    report = load(conn, desired, dry_run=False)
    assert report.committed
    assert (report.provinces.before, report.provinces.after) == (0, 5)
    assert report.provinces.inserted == 5
    assert (report.cities.before, report.cities.after) == (0, 5)
    assert report.cities.inserted == 5
    assert (report.suburbs.before, report.suburbs.after) == (0, 6)
    assert report.suburbs.inserted == 6


def test_second_load_is_a_no_op(conn, desired):
    load(conn, desired, dry_run=False)
    again = load(conn, desired, dry_run=False)
    assert again.provinces.inserted == again.provinces.updated == 0
    assert again.cities.inserted == again.cities.updated == 0
    assert again.suburbs.inserted == again.suburbs.updated == 0
    assert again.suburbs.unchanged == 6
    assert again.suburbs.after == 6


def test_dry_run_persists_nothing(conn, desired):
    report = load(conn, desired, dry_run=True)
    assert not report.committed
    assert report.suburbs.inserted == 6  # would-be
    n = conn.execute("SELECT count(*) FROM suburbs").fetchone()[0]
    assert n == 0


def test_spot_check_resolution_and_null_handling(conn, desired):
    load(conn, desired, dry_run=False)
    row = conn.execute(
        """
        SELECT s.name, s.slug, s.extension, s.postal_code, s.alternate_names,
               s.latitude, s.longitude, c.name AS city, p.name AS province, p.code
        FROM suburbs s
        JOIN cities c ON c.id = s.city_id
        JOIN provinces p ON p.id = c.province_id
        WHERE s.external_id = 1005
        """
    ).fetchone()
    name, slug, ext, postal, alt, lat, lon, city, province, code = row
    assert (name, ext, city, province, code) == (
        "Aberdeen",
        "Lotusville",
        "Aberdeen",
        "Eastern Cape",
        "EC",
    )
    assert slug == "aberdeen-lotusville"
    assert lat is None and lon is None

    blank_postal = conn.execute(
        "SELECT postal_code FROM suburbs WHERE external_id = 1006"
    ).fetchone()[0]
    assert blank_postal is None

    alt_name = conn.execute(
        "SELECT alternate_names FROM suburbs WHERE external_id = 1003"
    ).fetchone()[0]
    assert alt_name == "Sandton CBD"

    coords = conn.execute(
        "SELECT count(*) FROM suburbs WHERE latitude IS NOT NULL OR longitude IS NOT NULL"
    ).fetchone()[0]
    assert coords == 0


def test_only_south_african_provinces_land(conn, desired):
    load(conn, desired, dry_run=False)
    countries = conn.execute("SELECT DISTINCT country_code FROM provinces").fetchall()
    assert countries == [("ZA",)]
    names = {r[0] for r in conn.execute("SELECT name FROM provinces").fetchall()}
    assert names <= set(
        [
            "Eastern Cape",
            "Free State",
            "Gauteng",
            "KwaZulu Natal",
            "Limpopo",
            "Mpumalanga",
            "North West",
            "Northern Cape",
            "Western Cape",
        ]
    )


def test_updates_are_detected(conn, desired):
    load(conn, desired, dry_run=False)
    conn.execute("UPDATE suburbs SET postal_code = '0000' WHERE external_id = 1001")
    report = load(conn, desired, dry_run=False)
    assert report.suburbs.updated == 1
    assert report.suburbs.unchanged == 5
    restored = conn.execute(
        "SELECT postal_code FROM suburbs WHERE external_id = 1001"
    ).fetchone()[0]
    assert restored == "7708"


def test_missing_migration_is_reported(conn, desired):
    from iol_importers.property24.load import SchemaNotReadyError

    conn.execute("ALTER TABLE suburbs DROP COLUMN external_id")
    with pytest.raises(SchemaNotReadyError):
        load(conn, desired, dry_run=False)
