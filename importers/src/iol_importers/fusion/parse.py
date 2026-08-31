"""Parse a Fusion sync response (XML) into typed objects.

The Fusion sync methods return one of four root elements:

* ``<Changes>``          — a batch of sync events (``GetChanges``)
* ``<Exception type>``   — an error (any method)
* ``<RequestCompleted>`` — ``RequestSnapshot`` / ``RequestRollback`` / ``RequestListing``
* ``<ClientState>``      — ``GetClientState``

``xml.etree.ElementTree`` is used (stdlib): it resolves no external entities and
performs no I/O. The residual internal-entity-expansion risk is accepted for a
trusted vendor over TLS (see ``MAPPING_NOTES.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

_OBJECT_TAGS = frozenset({"Office", "Agent", "Listing", "Development", "AreaTree"})
_REF_TAGS: dict[str, str] = {
    "OfficeRef": "Office",
    "AgentRef": "Agent",
    "ListingRef": "Listing",
    "DevelopmentRef": "Development",
    "SuburbRef": "AreaTree",
    "ProvinceRef": "AreaTree",
    "CityRef": "AreaTree",
}


class FusionException(RuntimeError):
    """A Fusion ``<Exception type="…"/>`` response.

    ``type`` is the vendor's error code; ``attrib`` carries the rest of the
    element's attributes (e.g. ``commitToken`` on ``InvalidCommitToken``,
    ``paramName`` on ``InvalidParameter``).
    """

    def __init__(self, error_type: str, attrib: dict[str, str] | None = None) -> None:
        self.type = error_type
        self.attrib = dict(attrib or {})
        super().__init__(f"Fusion returned <Exception type={error_type!r}>")


class FusionParseError(RuntimeError):
    """The response body was not one of the four expected Fusion root elements."""


@dataclass(frozen=True, slots=True)
class SyncEvent:
    kind: str  # "CreateOrUpdate" | "Delete" | "Snapshot"
    object_type: str  # "Office" | "Agent" | "Listing" | "Development" | "AreaTree"
    element: Element  # the wrapped object element, or the *Ref element for a Delete
    sequence_id: int | None = None
    timestamp: str | None = None
    ref_id: str | None = None  # set for Delete


@dataclass(frozen=True, slots=True)
class ChangesBatch:
    client_id: str | None
    commit_token: str | None  # None => no more changes in the queue
    sync_events_count: int
    events: tuple[SyncEvent, ...]
    begin_snapshot: tuple[str, ...] | None = None  # the BeginSnapshot `types`, if present
    end_snapshot: bool = False
    rollback_to: str | None = None

    @property
    def drained(self) -> bool:
        return self.commit_token is None


@dataclass(frozen=True, slots=True)
class ClientState:
    client_id: str | None
    name: str | None
    type: str | None
    commit_token: str | None
    total_sync_events: int | None
    last_sync_event_sequence_id: int | None


def raise_for_exception(root: Element) -> None:
    """If ``root`` is (or wraps) a Fusion ``<Exception>``, raise ``FusionException``."""
    node = root if root.tag == "Exception" else root.find("Exception")
    if node is None:
        return
    error_type = node.get("type") or "Unknown"
    attrib = {k: v for k, v in node.attrib.items() if k != "type"}
    raise FusionException(error_type, attrib)


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _sync_event(kind: str, child: Element) -> SyncEvent | None:
    seq = _int_or_none(child.get("sequenceId"))
    ts = child.get("timestamp")
    inner = next((e for e in child if e.tag != "Exception"), None)
    if inner is None:
        return None
    if kind == "Delete":
        object_type = _REF_TAGS.get(inner.tag)
        if object_type is None:
            return None
        return SyncEvent(
            kind=kind,
            object_type=object_type,
            element=inner,
            sequence_id=seq,
            timestamp=ts,
            ref_id=inner.get("id"),
        )
    if inner.tag not in _OBJECT_TAGS:
        return None
    return SyncEvent(kind=kind, object_type=inner.tag, element=inner, sequence_id=seq, timestamp=ts)


def parse_changes(root: Element) -> ChangesBatch:
    """Parse a ``<Changes>`` element into a :class:`ChangesBatch`."""
    raise_for_exception(root)
    if root.tag != "Changes":
        raise FusionParseError(f"expected <Changes>, got <{root.tag}>")

    events: list[SyncEvent] = []
    begin_snapshot: tuple[str, ...] | None = None
    end_snapshot = False
    rollback_to: str | None = None

    for child in root:
        tag = child.tag
        if tag in ("CreateOrUpdate", "Delete", "Snapshot"):
            event = _sync_event(tag, child)
            if event is not None:
                events.append(event)
        elif tag == "BeginSnapshot":
            begin_snapshot = tuple(
                t.strip() for t in (child.get("types") or "").split(",") if t.strip()
            )
        elif tag == "EndSnapshot":
            end_snapshot = True
        elif tag == "Rollback":
            rollback_to = child.get("to")

    return ChangesBatch(
        client_id=root.get("clientId"),
        commit_token=root.get("commitToken"),
        sync_events_count=_int_or_none(root.get("syncEventsCount")) or 0,
        events=tuple(events),
        begin_snapshot=begin_snapshot,
        end_snapshot=end_snapshot,
        rollback_to=rollback_to,
    )


def parse_client_state(root: Element) -> ClientState:
    raise_for_exception(root)
    if root.tag != "ClientState":
        raise FusionParseError(f"expected <ClientState>, got <{root.tag}>")
    client = root.find("Client")
    sync_events = root.find("SyncEvents")
    c: dict[str, Any] = client.attrib if client is not None else {}
    s: dict[str, Any] = sync_events.attrib if sync_events is not None else {}
    return ClientState(
        client_id=c.get("clientId"),
        name=c.get("name"),
        type=c.get("type"),
        commit_token=root.get("commitToken"),
        total_sync_events=_int_or_none(s.get("totalSyncEvents")),
        last_sync_event_sequence_id=_int_or_none(s.get("lastSyncEventSequenceId")),
    )


def request_completed_warning(root: Element) -> str | None:
    """The ``warning`` attribute of a ``<RequestCompleted>`` response, if any."""
    raise_for_exception(root)
    if root.tag != "RequestCompleted":
        raise FusionParseError(f"expected <RequestCompleted>, got <{root.tag}>")
    return root.get("warning")
