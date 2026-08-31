"""Sample run — real Entegral pull, round-tripped through the Step 14 importer.

Pulls a bounded slice (two offices, a few listings each) live from
``sync.entegral.net``, imports into a throwaway schema, re-hosts the photos on a
temp media store, re-runs to show zero duplicates, and prints per-stage counts
plus the ``MAPPING_NOTES`` flag list. The checkpoint file is never touched.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.entegral.demo
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from iol_importers.config import resolve_entegral_credentials
from iol_importers.listings._scratch import ScratchDB, scratch_schema
from iol_importers.media.fetch import SourceUrlIndex
from iol_importers.media.store import MediaStore

from .adapter import format_result, run
from .client import EntegralClient

FEED = "demo-feed"
MAX_OFFICES = 2
MAX_LISTINGS = 5
FLAGGED = Path(__file__).parent / "MAPPING_NOTES.md"


def _pass(
    db: ScratchDB,
    client: EntegralClient,
    store: MediaStore,
    index: SourceUrlIndex,
    label: str,
) -> None:
    result = run(
        feed_source_code=FEED,
        max_offices=MAX_OFFICES,
        max_listings_per_office=MAX_LISTINGS,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        client=client,
        store=store,
        media_index=index,
        write_checkpoint=False,
    )
    print(f"\n{label}:\n{format_result(result)}")


def main() -> int:
    if resolve_entegral_credentials() is None:
        print(
            "ENTEGRAL_USERNAME / ENTEGRAL_PASSWORD are not set in .env.local — "
            "add the sandbox credentials and re-run."
        )
        return 1

    media_root = Path(tempfile.mkdtemp(prefix="entegral-demo-media-"))
    store = MediaStore(media_root)
    index = SourceUrlIndex(media_root)

    with EntegralClient() as client, scratch_schema() as db:
        offices = client.list_offices()
        print(f"officeslist: {len(offices)} offices")
        _pass(db, client, store, index, "pass 1 (initial import + re-host)")
        _pass(db, client, store, index, "pass 2 (same offices re-imported)")

        with db.connect() as conn:
            listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            media = conn.execute("SELECT count(*) AS n FROM listing_media").fetchone()["n"]
            errs = conn.execute("SELECT count(*) AS n FROM import_errors").fetchone()["n"]
            sample = conn.execute(
                "SELECT vendor_listing_id, primary_image_url FROM listings "
                "WHERE primary_image_url IS NOT NULL LIMIT 3"
            ).fetchall()
    print(f"\nlistings: {listings}   listing_media rows: {media}   import_errors: {errs}")
    print(f"re-hosted media root: {media_root}")
    for row in sample:
        print(f"  {row['vendor_listing_id']} -> {row['primary_image_url']}")

    notes = FLAGGED.read_text()
    flagged = notes.split("## Deliberately not mapped", 1)[1].split("##", 1)[0].strip()
    print("\nfields left unmapped rather than guessed (see entegral/MAPPING_NOTES.md):\n")
    print(flagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
