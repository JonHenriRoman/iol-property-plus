"""Runnable proof of the feed-tracking scaffolding.

Builds the Domain 6 tables in a throwaway schema on ``TEST_DATABASE_URL``, seeds
one ``feed_sources`` row, then does two runs:

  A. a set of fake records where several fail with different ``error_type`` values
     (nothing raised) -> the job closes ``PartialSuccess``;
  B. a run that raises part-way through -> the job closes ``Failed`` and the
     exception propagates (caught here only so the script can print the row).

Then it prints every ``import_jobs`` and ``import_errors`` row and drops the schema.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.feeds.demo
"""

from __future__ import annotations

import json
from typing import Any

from ._scratch import scratch_schema
from .run import import_run

# Fake feed records. "ok" rows succeed; the rest each fail a different way.
_RECORDS: list[dict[str, Any]] = [
    {"id": "L-1001", "outcome": "insert", "beds": 3},
    {"id": "L-1002", "outcome": "update", "beds": 2},
    {"id": "L-1003", "outcome": "validation", "beds": -1},
    {"id": "L-1004", "outcome": "parse", "beds": "three"},
    {"id": "L-1005", "outcome": "db_insert", "beds": 4},
    {"id": "L-1006", "outcome": "mapping", "beds": 1},
    {"id": "L-1007", "outcome": "skip", "beds": 5},
]


def _run_a(connect: Any) -> int:
    with import_run("demo-feed", connect=connect, file_reference="demo-batch-A.xml") as run:
        for rec in _RECORDS:
            run.seen()
            outcome = rec["outcome"]
            if outcome == "insert":
                run.inserted()
            elif outcome == "update":
                run.updated()
            elif outcome == "skip":
                run.skipped()
            else:
                run.record_error(
                    vendor_listing_id=rec["id"],
                    error_type=outcome,
                    error_message=f"{outcome} failed for {rec['id']}",
                    raw_payload=rec,  # exact record as received
                )
        return run.job_id


def _run_b(connect: Any) -> int:
    captured: dict[str, int] = {}
    try:
        with import_run("demo-feed", connect=connect, file_reference="demo-batch-B.xml") as run:
            captured["job_id"] = run.job_id
            run.seen()
            run.inserted()
            run.seen()
            # raw bytes payload, stored verbatim as a JSON string scalar
            run.record_error(
                vendor_listing_id="L-2002",
                error_type="parse",
                error_message="malformed price node",
                raw_payload=b"<listing><price>R 1,2M</price></listing>",
            )
            raise RuntimeError("feed connection dropped at record 3")
    except RuntimeError as exc:
        print(f"  run B raised as expected: {exc}")
    return captured["job_id"]


def _dump(connect: Any) -> None:
    with connect() as conn:
        jobs = conn.execute(
            """
            SELECT id, feed_source_id, status, records_seen, records_inserted,
                   records_updated, records_skipped, records_expired, records_failed,
                   error_message, file_reference,
                   (finished_at IS NOT NULL) AS finished
            FROM import_jobs ORDER BY id
            """
        ).fetchall()
        errors = conn.execute(
            """
            SELECT id, import_job_id, vendor_listing_id, error_type, error_message, raw_payload
            FROM import_errors ORDER BY id
            """
        ).fetchall()

    print("\nimport_jobs:")
    for row in jobs:
        print("  " + json.dumps(row, default=str))
    print("\nimport_errors:")
    for row in errors:
        print("  " + json.dumps(row, default=str))


def main() -> int:
    with scratch_schema() as connect:
        with connect() as conn:
            conn.execute(
                "INSERT INTO feed_sources (code, name) VALUES ('demo-feed', 'Demo Feed')"
            )
        job_a = _run_a(connect)
        job_b = _run_b(connect)
        print(f"\nrun A -> import_jobs.id={job_a}   run B -> import_jobs.id={job_b}")
        _dump(connect)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
