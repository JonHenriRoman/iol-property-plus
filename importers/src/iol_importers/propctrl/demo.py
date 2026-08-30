"""Sample run — real PropCtrl fetch, round-tripped through the Step 14 importer.

Pulls a bounded slice of the change feed live from ``api.propctrl.com``, imports
the ``Active`` listings into a throwaway schema, re-imports to show zero
duplicates, and prints per-stage counts plus the ``MAPPING_NOTES`` flag list.
The checkpoint file is never touched.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.propctrl.demo
"""

from __future__ import annotations

from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run
from .client import PropctrlClient

FEED = "demo-feed"
MAX_LISTINGS = 60
# A recent window keeps the demo bounded and the listings mostly still Active.
FROM_DATE = "2026-08-25T00:00:00Z"
FLAGGED = Path(__file__).parent / "MAPPING_NOTES.md"


def _pass(db: ScratchDB, client: PropctrlClient, label: str) -> None:
    result = run(
        feed_source_code=FEED,
        from_date=FROM_DATE,
        max_listings=MAX_LISTINGS,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        write_checkpoint=False,
        client=client,
    )
    print(f"\n{label}:\n{format_result(result)}")


def main() -> int:
    with PropctrlClient() as client, scratch_schema() as db:
        client.echo()
        print("credentials verified against /admin/echo-authenticated")
        _pass(db, client, "pass 1 (initial import)")
        _pass(db, client, "pass 2 (same window re-imported)")

        with db.connect() as conn:
            total = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            errs = conn.execute("SELECT count(*) AS n FROM import_errors").fetchone()["n"]
        print(f"\nlistings rows after two passes: {total}   import_errors: {errs}")

    notes = FLAGGED.read_text()
    flagged = notes.split("## Deliberately not mapped", 1)[1].split("##", 1)[0].strip()
    print("\nfields left unmapped rather than guessed (see propctrl/MAPPING_NOTES.md):\n")
    print(flagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
