"""Offline guard-rail tests for the expiry sweep — no database."""

from __future__ import annotations

import re

from iol_importers.lifecycle.expire import _EXPIRE_SQL, ExpiryResult


def test_sql_only_expires_active_rows():
    assert "status = 'Active'" in _EXPIRE_SQL


def test_sql_filters_on_live_expiry():
    assert "expires_at < now()" in _EXPIRE_SQL


def test_sql_sets_status_and_expired_at_only():
    assert "SET status = 'Expired', expired_at = now()" in _EXPIRE_SQL


def test_sql_never_deletes_and_never_writes_expires_at():
    lowered = _EXPIRE_SQL.lower()
    assert "delete" not in lowered
    # the only "expires_at" is the read in the WHERE clause, never an assignment
    assert not re.search(r"set\b[^;]*\bexpires_at\s*=", lowered, re.DOTALL)


def test_expiry_result_shape():
    result = ExpiryResult(expired_count=2, status_before={"Active": 5}, status_after={"Active": 3})
    assert result.expired_count == 2
    assert result.status_before == {"Active": 5}
    assert result.status_after == {"Active": 3}
