"""Sample run — real RE/MAX fetch, round-tripped through the Step 14 importer.

Runs all three sync paths against the live API, bounded: a few agents (full),
one page of changes (incremental), and the deletions pass. Round-trips through a
throwaway schema, re-runs to show zero duplicates + the unchanged-skip, and
prints per-path counts and the MAPPING_NOTES flag list. The checkpoint file is
never touched.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.remax.demo
"""

from __future__ import annotations

from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run
from .client import RemaxClient

FEED = "demo-feed"
START_DATE = "2026-08-28 00:00:00"
FLAGGED = Path(__file__).parent / "MAPPING_NOTES.md"


def _pass(db: ScratchDB, client: RemaxClient, mode: str, label: str) -> None:
    result = run(
        feed_source_code=FEED,
        mode=mode,
        start_date=START_DATE if mode == "incremental" else None,
        max_pages=1,
        max_agents=3 if mode == "full" else None,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
        write_checkpoint=False,
        client=client,
    )
    print(f"\n{label}:\n{format_result(result)}")


def main() -> int:
    with RemaxClient() as client, scratch_schema() as db:
        client.list_office_ids()  # a signed call — proves auth
        print("SigV4 + x-api-key verified against /lists")
        _pass(db, client, "full", "full sync (3 agents, 1 page each)")
        _pass(db, client, "incremental", "incremental (1 page)")
        _pass(db, client, "incremental", "incremental re-run (zero duplicates / skip)")

        with db.connect() as conn:
            total = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            errs = conn.execute("SELECT count(*) AS n FROM import_errors").fetchone()["n"]
            withdrawn = conn.execute(
                "SELECT count(*) AS n FROM listings WHERE status = 'Withdrawn'"
            ).fetchone()["n"]
        print(
            f"\nlistings rows: {total}   import_errors: {errs}   "
            f"soft-deleted (Withdrawn): {withdrawn}"
        )

    notes = FLAGGED.read_text()
    flagged = notes.split("## Deliberately not mapped", 1)[1].split("##", 1)[0].strip()
    print("\nfields left unmapped rather than guessed (see remax/MAPPING_NOTES.md):\n")
    print(flagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
