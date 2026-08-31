"""An httpx.MockTransport that plays a sequence of Fusion ``<Changes>`` fixtures.

The mock is a small state machine mirroring the doc's commitToken rules:

* ``GetChanges`` with **no** ``commitToken`` -> re-serve the current batch (first
  call / replay).
* ``GetChanges`` acknowledging the current batch's token -> advance, serve the next.
* ``GetChanges`` with a wrong token -> ``<Exception type="InvalidCommitToken">``.

``arm_exception(name)`` makes the next ``GetChanges`` return that fixture once.
Every request is checked for the four security-token query params.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs
from xml.etree.ElementTree import fromstring

import httpx

FIXTURES = Path(__file__).resolve().parents[1] / "src/iol_importers/fusion/fixtures"

_SNAPSHOT_SEQUENCE = ("snapshot_1", "snapshot_2", "snapshot_3", "drained")
_DELTA_SEQUENCE = ("delta_1", "drained")


def load(name: str) -> str:
    return (FIXTURES / f"{name}.xml").read_text()


class FusionMockServer:
    def __init__(self, sequence: tuple[str, ...]) -> None:
        self.sequence = sequence
        self.pos = 0
        self.snapshot_requested = 0
        self.rollback_requested = 0
        self.get_changes_calls: list[str | None] = []
        self._armed: str | None = None

    def arm_exception(self, fixture_name: str) -> None:
        self._armed = fixture_name

    def _current(self) -> str:
        return load(self.sequence[self.pos])

    def _token_of(self, body: str) -> str | None:
        return fromstring(body).get("commitToken")

    def handle(self, request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        for param in ("clientId", "timeStamp", "salt", "digest"):
            assert query.get(param), f"missing security param {param}"
        method = request.url.path.rsplit("/", 1)[-1]

        if method == "RequestSnapshot":
            self.snapshot_requested += 1
            return httpx.Response(200, text=load("request_completed"))
        if method == "RequestRollback":
            self.rollback_requested += 1
            return httpx.Response(200, text="<RequestCompleted />")
        if method == "RequestListing":
            return httpx.Response(200, text="<RequestCompleted />")
        if method == "GetClientState":
            return httpx.Response(200, text=load("client_state"))
        if method != "GetChanges":
            return httpx.Response(404, text=f'<Exception type="UnknownMethod" method="{method}" />')

        if self._armed is not None:
            fixture, self._armed = self._armed, None
            return httpx.Response(200, text=load(fixture))

        form = parse_qs(request.content.decode())
        token = (form.get("commitToken") or [None])[0] or None
        self.get_changes_calls.append(token)

        current = self._current()
        current_token = self._token_of(current)
        if token is None:
            return httpx.Response(200, text=current)
        if token == current_token:
            self.pos = min(self.pos + 1, len(self.sequence) - 1)
            return httpx.Response(200, text=self._current())
        return httpx.Response(
            200,
            text=(
                f'<Exception type="InvalidCommitToken" invalidCommitToken="{token}" '
                f'commitToken="{current_token}" />'
            ),
        )


def mock_transport(
    sequence: tuple[str, ...] = _SNAPSHOT_SEQUENCE,
) -> tuple[httpx.MockTransport, FusionMockServer]:
    server = FusionMockServer(sequence)
    return httpx.MockTransport(server.handle), server


def snapshot_transport() -> tuple[httpx.MockTransport, FusionMockServer]:
    return mock_transport(_SNAPSHOT_SEQUENCE)


def delta_transport() -> tuple[httpx.MockTransport, FusionMockServer]:
    return mock_transport(_DELTA_SEQUENCE)
