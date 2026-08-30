"""Offline tests for the feed-tracking scaffolding — no database, no network."""

from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from iol_importers.feeds.run import ImportRun, RunCounts, _as_jsonb


class FakeConn:
    """Records every execute() call as (sql, params)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))


@pytest.fixture
def run() -> ImportRun:
    return ImportRun(conn=FakeConn(), job_id=7, feed_source_id=3)


def test_counts_start_at_zero(run: ImportRun):
    assert run.counts == RunCounts()


def test_counters_accumulate(run: ImportRun):
    run.seen(5)
    run.inserted()
    run.inserted()
    run.updated(3)
    run.skipped()
    run.expired(2)
    assert run.counts == RunCounts(seen=5, inserted=2, updated=3, skipped=1, expired=2, failed=0)


def test_counts_is_a_snapshot(run: ImportRun):
    run.seen()
    first = run.counts
    run.seen()
    assert first.seen == 1
    assert run.counts.seen == 2


def test_record_error_writes_one_row_and_counts_the_failure(run: ImportRun):
    payload = {"id": "L-9", "raw": True}
    run.record_error(
        vendor_listing_id="L-9",
        error_type="validation",
        error_message="beds < 0",
        raw_payload=payload,
    )
    assert run.counts.failed == 1
    assert len(run._conn.calls) == 1
    sql, params = run._conn.calls[0]
    assert "INSERT INTO import_errors" in sql
    assert params[0] == 7  # import_job_id
    assert params[1] == 3  # feed_source_id
    assert params[2] == "L-9"
    assert params[3] == "validation"
    assert isinstance(params[5], Jsonb)
    assert params[5].obj is payload  # exact object, untransformed


def test_record_error_rejects_an_unknown_error_type(run: ImportRun):
    with pytest.raises(ValueError, match="error_type"):
        run.record_error(
            vendor_listing_id="x",
            error_type="explosion",  # type: ignore[arg-type]
            error_message="nope",
            raw_payload={},
        )
    assert run.counts.failed == 0
    assert run._conn.calls == []


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"a": 1}, {"a": 1}),
        ([1, 2, 3], [1, 2, 3]),
        ("just a string", "just a string"),
        (b"<xml/>", "<xml/>"),
        (None, None),
    ],
)
def test_as_jsonb_passes_payload_through_verbatim(payload: object, expected: object):
    wrapped = _as_jsonb(payload)
    assert isinstance(wrapped, Jsonb)
    assert wrapped.obj == expected
