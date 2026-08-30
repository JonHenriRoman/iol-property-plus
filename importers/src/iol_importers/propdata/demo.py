"""Sample run — real Propdata fetch, round-tripped through the Step 14 importer.

Pulls page 1 of residential / commercial / projects live from ``harcourts.co.za``
(the only client with three of the four categories populated) plus a holiday
fixture (the account has no holiday stock), imports each into a throwaway schema,
re-imports to show zero duplicates, and prints per-category counts.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.propdata.demo
"""

from __future__ import annotations

import json
from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema
from iol_importers.listings.importer import import_listings

from .adapter import format_counts, run
from .client import PropdataClient
from .map import to_import_record

SITE = "harcourts.co.za"
FEED = "demo-feed"
FIXTURES = Path(__file__).parent / "fixtures"


def _holiday_records(client: PropdataClient) -> list[dict]:
    raw = json.loads((FIXTURES / "holiday_page1.json").read_text())["results"]
    return [to_import_record(r, category="holiday", client=client) for r in raw]


def _import_holiday(db: ScratchDB, records: list[dict]):
    return import_listings(
        records,
        feed_source_code=FEED,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        file_reference=f"propdata:{SITE}:holiday",
    )


def _pass(db: ScratchDB, client: PropdataClient, label: str) -> None:
    results = run(
        site_domain=SITE,
        feed_source_code=FEED,
        categories=("residential", "commercial", "projects"),
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        page_limit=1,
        client=client,
    )
    results["holiday"] = _import_holiday(db, _holiday_records(client))
    print(f"\n{label}:\n{format_counts(results)}")


def main() -> int:
    with PropdataClient(SITE) as client, scratch_schema() as db:
        client.ensure_token()
        print(f"authenticated for {SITE}; token renewed/stored server-side (not shown)")
        _pass(db, client, "pass 1 (initial import)")
        _pass(db, client, "pass 2 (same pages re-imported)")

        with db.connect() as conn:
            total = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            errs = conn.execute("SELECT count(*) AS n FROM import_errors").fetchone()["n"]
        print(f"\nlistings rows after two passes: {total}   import_errors: {errs}")

    notes = (FIXTURES.parent / "MAPPING_NOTES.md").read_text()
    flagged = notes.split("## Flagged", 1)[1].split("\n", 1)[1].split("## Auth", 1)[0].strip()
    print("\nfields left unmapped rather than guessed (see propdata/MAPPING_NOTES.md):\n")
    print(flagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
