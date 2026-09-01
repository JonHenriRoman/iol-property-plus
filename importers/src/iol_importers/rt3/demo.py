"""Sample run — the bundled 2-province fixtures, round-tripped through Step 14.

Parses ``fixtures/iol-Gauteng.txt`` and ``fixtures/iol-Western_Cape.txt`` with the
shared bracket-KV parser, imports both in one job into a throwaway schema, re-runs
to show zero duplicates, then re-runs against the Gauteng file with one listing
removed to show the per-province soft-delete. No network.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.rt3.demo
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run

FEED = "demo-feed"
FIXTURES = Path(__file__).parent / "fixtures"
GAUTENG = FIXTURES / "iol-Gauteng.txt"
WESTERN_CAPE = FIXTURES / "iol-Western_Cape.txt"
_OPEN = "[[Listing_Start]]"


def _pass(db: ScratchDB, label: str, files: dict[str, str]) -> None:
    result = run(
        feed_source_code=FEED,
        files=files,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )
    print(f"\n{label}:\n{format_result(result)}")


def _gauteng_without(reference: str) -> str:
    head, _, rest = GAUTENG.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"[[Reference:{reference}/]]" not in b]
    tmp = Path(tempfile.mkdtemp()) / "iol-Gauteng.txt"
    tmp.write_text(head + "".join(kept))
    return str(tmp)


def main() -> int:
    both = {"Gauteng": str(GAUTENG), "Western_Cape": str(WESTERN_CAPE)}
    with scratch_schema() as db:
        _pass(db, "pass 1 (initial import, both provinces)", both)
        _pass(db, "pass 2 (same files re-imported)", both)
        _pass(
            db,
            "pass 3 (1289051 removed from Gauteng only)",
            {"Gauteng": _gauteng_without("1289051"), "Western_Cape": str(WESTERN_CAPE)},
        )

        with db.connect() as conn:
            listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            media = conn.execute("SELECT count(*) AS n FROM listing_media").fetchone()["n"]
            agents = conn.execute("SELECT count(*) AS n FROM agents").fetchone()["n"]
            by_status = conn.execute(
                "SELECT status, count(*) AS n FROM listings GROUP BY status ORDER BY status"
            ).fetchall()
            by_province = conn.execute(
                "SELECT raw_data->>'rt3_province' AS p, count(*) AS n "
                "FROM listings GROUP BY 1 ORDER BY 1"
            ).fetchall()
            errs = conn.execute(
                "SELECT error_type, count(*) AS n FROM import_errors GROUP BY error_type"
            ).fetchall()

    print(f"\nlistings: {listings}   listing_media: {media}   agents: {agents}")
    print("by status: " + ", ".join(f"{r['status']}={r['n']}" for r in by_status))
    print("by province: " + ", ".join(f"{r['p']}={r['n']}" for r in by_province))
    print("import_errors: " + (", ".join(f"{r['error_type']}={r['n']}" for r in errs) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
