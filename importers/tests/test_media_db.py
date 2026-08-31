"""Opt-in DB test — media.sync_listing_media upsert + prune.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from iol_importers.media.db import sync_listing_media
from iol_importers.media.store import MediaStore

pytestmark = pytest.mark.dbtest

IMG = Path(__file__).resolve().parents[1] / "src/iol_importers/entegral/fixtures/img"
FEED = "demo-feed"


@pytest.fixture
def db():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from iol_importers.listings._scratch import scratch_schema

    with scratch_schema() as scratch:
        yield scratch


def _listing(db) -> str:
    with db.connect() as conn:
        fsid = conn.execute("SELECT id FROM feed_sources WHERE code = %s", (FEED,)).fetchone()["id"]
        ptid = conn.execute("SELECT id FROM property_types LIMIT 1").fetchone()["id"]
        lid = conn.execute(
            "INSERT INTO listings (feed_source_id, vendor_listing_id, property_type_id, title) "
            "VALUES (%s, 'L1', %s, 't') RETURNING id",
            (fsid, ptid),
        ).fetchone()["id"]
        conn.commit()
    return lid


def test_sync_inserts_updates_and_prunes(db, tmp_path):
    store = MediaStore(tmp_path)
    a = store.put((IMG / "sample.jpg").read_bytes(), feed="entegral")
    b = store.put((IMG / "sample.png").read_bytes(), feed="entegral")
    c = store.put((IMG / "second.png").read_bytes(), feed="entegral")
    lid = _listing(db)

    conn = db.data_connect()
    try:
        with conn.transaction():
            first = sync_listing_media(conn.cursor(), lid, [a, b, c])
        assert (first.inserted, first.pruned) == (3, 0)

        # second pass: b dropped, a + c re-ordered
        with conn.transaction():
            second = sync_listing_media(conn.cursor(), lid, [c, a])
        assert second.inserted == 0
        assert second.updated == 2
        assert second.pruned == 1
    finally:
        conn.close()

    with db.connect() as conn:
        rows = conn.execute(
            "SELECT url, display_order FROM listing_media "
            "WHERE listing_id = %s ORDER BY display_order",
            (lid,),
        ).fetchall()
    assert [r["url"] for r in rows] == [c.url, a.url]
    assert [r["display_order"] for r in rows] == [0, 1]
