"""Sample run — the bundled fixture feed, round-tripped through the Step 14 importer.

Parses ``fixtures/feed.txt`` with the shared bracket-KV parser, imports into a
throwaway schema, re-runs to show zero duplicates, then re-runs against the feed
with one listing removed to show the soft-delete. No network, no token.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.myroof.demo
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run

FEED = "demo-feed"
FIXTURE = Path(__file__).parent / "fixtures" / "feed.txt"
_OPEN = "[[Listing_Start]]"


def _pass(db: ScratchDB, label: str, path: str) -> None:
    result = run(
        feed_source_code=FEED,
        token="demo-token",
        file=path,
        connect=db.data_connect,
        tracking_connect=db.tracking_connect,
    )
    print(f"\n{label}:\n{format_result(result)}")


def _feed_without(reference: str) -> str:
    head, _, rest = FIXTURE.read_text().partition(_OPEN)
    blocks = (_OPEN + b for b in rest.split(_OPEN) if b.strip())
    kept = [b for b in blocks if f"[[Reference:{reference}/]]" not in b]
    tmp = Path(tempfile.mkdtemp()) / "feed_removed_one.txt"
    tmp.write_text(head + "".join(kept))
    return str(tmp)


def main() -> int:
    with scratch_schema() as db:
        _pass(db, "pass 1 (initial import)", str(FIXTURE))
        _pass(db, "pass 2 (same feed re-imported)", str(FIXTURE))
        _pass(db, "pass 3 (MR300001 removed from feed)", _feed_without("MR300001"))

        with db.connect() as conn:
            listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            media = conn.execute("SELECT count(*) AS n FROM listing_media").fetchone()["n"]
            agents = conn.execute("SELECT count(*) AS n FROM agents").fetchone()["n"]
            by_status = conn.execute(
                "SELECT status, count(*) AS n FROM listings GROUP BY status ORDER BY status"
            ).fetchall()
            errs = conn.execute(
                "SELECT error_type, count(*) AS n FROM import_errors GROUP BY error_type"
            ).fetchall()

    print(f"\nlistings: {listings}   listing_media: {media}   agents: {agents}")
    print("by status: " + ", ".join(f"{r['status']}={r['n']}" for r in by_status))
    print("import_errors: " + (", ".join(f"{r['error_type']}={r['n']}" for r in errs) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
