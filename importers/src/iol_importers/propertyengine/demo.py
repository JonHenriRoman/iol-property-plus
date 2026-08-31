"""Sample run — the bundled fixture feed, round-tripped through the Step 14 importer.

Decodes ``fixtures/feed.xml`` (the real feed's XML shape), imports into a throwaway
schema, re-runs to show zero duplicates, and prints per-stage counts plus the
``MAPPING_NOTES`` "not mapped" list. No network, no credentials.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.propertyengine.demo
"""

from __future__ import annotations

from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run

FEED = "demo-feed"
FIXTURE = Path(__file__).parent / "fixtures" / "feed.xml"
NOTES = Path(__file__).parent / "MAPPING_NOTES.md"


def _pass(db: ScratchDB, label: str) -> None:
    result = run(
        feed_source_code=FEED,
        file=str(FIXTURE),
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )
    print(f"\n{label}:\n{format_result(result)}")


def main() -> int:
    with scratch_schema() as db:
        _pass(db, "pass 1 (initial import)")
        _pass(db, "pass 2 (same file re-imported)")

        with db.connect() as conn:
            listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            media = conn.execute("SELECT count(*) AS n FROM listing_media").fetchone()["n"]
            errs = conn.execute(
                "SELECT error_type, count(*) AS n FROM import_errors GROUP BY error_type"
            ).fetchall()
            by_type = conn.execute(
                """
                SELECT l.listing_type, count(*) AS n
                FROM listings l GROUP BY l.listing_type ORDER BY l.listing_type
                """
            ).fetchall()
            pair = conn.execute(
                """
                SELECT vendor_listing_id, suburb_id
                FROM listings WHERE vendor_listing_id IN ('900001', '900002')
                ORDER BY vendor_listing_id
                """
            ).fetchall()

    print(f"\nlistings: {listings}   listing_media rows: {media}")
    print("import_errors: " + (", ".join(f"{r['error_type']}={r['n']}" for r in errs) or "none"))
    print("by listing_type: " + ", ".join(f"{r['listing_type']}={r['n']}" for r in by_type))
    detail = ", ".join(f"{r['vendor_listing_id']}->suburb {r['suburb_id']}" for r in pair)
    same = bool(pair) and len({r["suburb_id"] for r in pair}) == 1
    print(f"Location vs free-text resolve to the same suburb: {'yes' if same else 'NO'} ({detail})")

    section = NOTES.read_text().split("## Deliberately not mapped", 1)[1]
    not_mapped = section.split("##", 1)[0].strip()
    print("\ndeliberately not mapped (see propertyengine/MAPPING_NOTES.md):\n")
    print(not_mapped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
