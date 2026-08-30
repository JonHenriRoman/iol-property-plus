"""Opt-in database tests for the feed-tracking scaffolding.

Skipped unless TEST_DATABASE_URL is set. Never touches iol_property_plus: every
test runs against a throwaway schema created and dropped by ``scratch_schema``.
Unlike the property24 tests, these cannot roll back — the whole point of the
scaffolding is that tracking rows commit — so isolation is by schema instead.

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers pytest -m dbtest
"""

from __future__ import annotations

import os

import pytest

from iol_importers.feeds._scratch import scratch_schema
from iol_importers.feeds.run import (
    FeedSourceNotFoundError,
    ImportRun,
    SchemaNotReadyError,
    import_run,
)

pytestmark = pytest.mark.dbtest


@pytest.fixture
def connect():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    with scratch_schema() as factory:
        with factory() as conn:
            conn.execute("INSERT INTO feed_sources (code, name) VALUES ('t-feed', 'Test Feed')")
        yield factory


def _job(connect, job_id: int) -> dict:
    with connect() as conn:
        return conn.execute("SELECT * FROM import_jobs WHERE id = %s", (job_id,)).fetchone()


def _errors(connect, job_id: int) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM import_errors WHERE import_job_id = %s ORDER BY id", (job_id,)
        ).fetchall()


def _all_jobs(connect) -> list[dict]:
    with connect() as conn:
        return conn.execute("SELECT * FROM import_jobs ORDER BY id").fetchall()


def test_partial_success_with_per_record_failures(connect):
    payloads = [
        {"id": "A", "kind": "validation"},
        {"id": "B", "kind": "parse"},
        {"id": "C", "kind": "mapping"},
    ]
    with import_run("t-feed", connect=connect) as run:
        run.seen(6)
        run.inserted(2)
        run.updated(1)
        for p in payloads:
            run.record_error(
                vendor_listing_id=p["id"],
                error_type=p["kind"],
                error_message=f"{p['kind']} on {p['id']}",
                raw_payload=p,
            )
        job_id = run.job_id

    assert len(_all_jobs(connect)) == 1
    job = _job(connect, job_id)
    assert job["status"] == "PartialSuccess"
    assert job["finished_at"] is not None
    assert job["error_message"] is None
    assert (job["records_seen"], job["records_inserted"], job["records_updated"]) == (6, 2, 1)
    assert job["records_failed"] == 3

    errors = _errors(connect, job_id)
    assert len(errors) == 3
    assert [e["error_type"] for e in errors] == ["validation", "parse", "mapping"]
    assert [e["raw_payload"] for e in errors] == payloads  # byte-identical to the input
    assert all(e["feed_source_id"] == job["feed_source_id"] for e in errors)


def test_clean_run_closes_success(connect):
    with import_run("t-feed", connect=connect) as run:
        run.seen(3)
        run.inserted(3)
        job_id = run.job_id
    assert _job(connect, job_id)["status"] == "Success"


def test_exception_mid_run_still_closes_failed(connect):
    with pytest.raises(RuntimeError, match="boom"), import_run("t-feed", connect=connect) as run:
        run.seen(2)
        run.inserted(1)
        run.record_error(
            vendor_listing_id="X",
            error_type="db_insert",
            error_message="constraint",
            raw_payload={"id": "X"},
        )
        raise RuntimeError("boom at record 3")

    jobs = _all_jobs(connect)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["status"] == "Failed"
    assert job["finished_at"] is not None
    assert job["error_message"] == "RuntimeError: boom at record 3"
    # counts accumulated before the throw are preserved
    assert (job["records_seen"], job["records_inserted"], job["records_failed"]) == (2, 1, 1)
    assert len(_errors(connect, job["id"])) == 1
    # nothing left mid-flight
    assert not [j for j in jobs if j["status"] == "Running"]


def test_unknown_feed_source_creates_no_job(connect):
    with pytest.raises(FeedSourceNotFoundError), import_run("no-such-feed", connect=connect):
        pass
    assert _all_jobs(connect) == []


def test_missing_migration_is_reported_and_creates_no_job(connect):
    with connect() as conn:
        conn.execute("ALTER TABLE import_jobs DROP COLUMN records_skipped")
    with pytest.raises(SchemaNotReadyError, match="records_skipped"), import_run(
        "t-feed", connect=connect
    ):
        pass
    with connect() as conn:
        remaining = conn.execute("SELECT count(*) AS n FROM import_jobs").fetchone()["n"]
    assert remaining == 0


def test_import_run_yields_the_handle(connect):
    with import_run("t-feed", connect=connect) as run:
        assert isinstance(run, ImportRun)
        assert run.job_id > 0
        assert run.feed_source_id > 0
