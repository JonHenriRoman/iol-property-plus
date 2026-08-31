"""Offline unit tests — Fusion XML -> typed events."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

import pytest

from fusion_mock import load
from iol_importers.fusion.parse import (
    FusionException,
    FusionParseError,
    parse_changes,
    parse_client_state,
    raise_for_exception,
    request_completed_warning,
)


def _changes(name: str):
    return parse_changes(fromstring(load(name)))


def test_snapshot_batch_events_and_markers():
    batch = _changes("snapshot_1")
    assert batch.commit_token == "snap-token-1"
    assert batch.begin_snapshot == ("Offices", "Agents", "AreaTree", "Developments", "Listings")
    assert batch.end_snapshot is False
    kinds = [(e.kind, e.object_type) for e in batch.events]
    assert kinds == [("Snapshot", "Office"), ("Snapshot", "Agent"), ("Snapshot", "Listing")]


def test_end_snapshot_marker():
    batch = _changes("snapshot_3")
    assert batch.end_snapshot is True
    assert [e.object_type for e in batch.events] == ["AreaTree", "Development"]


def test_delta_batch_create_and_deletes():
    batch = _changes("delta_1")
    assert batch.sync_events_count == 4
    assert [(e.kind, e.object_type, e.ref_id) for e in batch.events] == [
        ("CreateOrUpdate", "Listing", None),
        ("Delete", "Listing", "101"),
        ("Delete", "Office", "4"),
        ("Delete", "Agent", "441"),
    ]
    assert batch.events[0].sequence_id == 500
    assert batch.events[0].timestamp == "2026-08-30T10:00:00.00Z"


def test_drained_response_has_no_commit_token():
    batch = _changes("drained")
    assert batch.commit_token is None
    assert batch.drained is True
    assert batch.events == ()


def test_exception_response_raises_with_attrib():
    with pytest.raises(FusionException) as exc:
        _changes("exc_invalid_commit_token")
    assert exc.value.type == "InvalidCommitToken"
    assert exc.value.attrib["commitToken"] == "delta-token-1"
    assert "type" not in exc.value.attrib


def test_housekeeping_exception():
    with pytest.raises(FusionException) as exc:
        raise_for_exception(fromstring(load("exc_housekeeping")))
    assert exc.value.type == "HousekeepingInProgress"


def test_client_state_parses():
    state = parse_client_state(fromstring(load("client_state")))
    assert state.name == "IOL"
    assert state.type == "PortalSync"
    assert state.client_id == "458"
    assert state.commit_token == "6916f4ede4fddb1574655e14"
    assert state.total_sync_events == 185
    assert state.last_sync_event_sequence_id == 1620


def test_request_completed_warning():
    assert (
        request_completed_warning(fromstring(load("request_completed")))
        == "ExistingSnapshotAborted"
    )


def test_wrong_root_element_raises_parse_error():
    with pytest.raises(FusionParseError):
        parse_changes(fromstring("<ClientState />"))
