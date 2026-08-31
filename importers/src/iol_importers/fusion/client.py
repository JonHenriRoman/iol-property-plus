"""Fusion FeedStore sync client — the four POST methods, XML dispatch, retries,
and the persisted commit-token state.

Every call carries a **fresh** SecurityToken (query string); ``GetChanges`` /
``RequestRollback`` also send a small form body. Responses are XML; ``_post``
returns the parsed root element and raises :class:`~.parse.FusionException` for an
``<Exception>`` body. ``HousekeepingInProgress`` and transient service errors are
retried here with back-off; the commit-token exceptions (``InvalidCommitToken`` /
``CommitTokenExpired``) propagate to the adapter, which owns the loop state.

Credentials live in a private attribute; ``__repr__`` and every log line redact
the password and never carry a digest.
"""

from __future__ import annotations

import json
import logging
import stat
import time
from dataclasses import dataclass, field
from typing import Any
from xml.etree.ElementTree import Element, ParseError, fromstring

import httpx

from iol_importers.config import FUSION_DIR, FusionCredentials, resolve_fusion_credentials

from .parse import (
    ChangesBatch,
    ClientState,
    FusionException,
    parse_changes,
    parse_client_state,
    raise_for_exception,
    request_completed_warning,
)
from .security import security_params

logger = logging.getLogger("iol_importers.fusion")

# Exceptions worth retrying inside the client (with a delay). Everything else —
# InvalidClientID, InvalidParameter, InvalidCommitToken, CommitTokenExpired —
# propagates immediately.
_HOUSEKEEPING = "HousekeepingInProgress"
_TRANSIENT_EXCEPTIONS = frozenset(
    {
        _HOUSEKEEPING,
        "ServiceOffline",
        "InternalError",
        "SecurityTokenExpired",
        "InvalidSecurityToken",
    }
)


class FusionAPIError(RuntimeError):
    """A Fusion endpoint returned a non-XML error or exhausted retries."""


class FusionCredentialsError(FusionAPIError):
    """FUSION_CLIENT_ID / FUSION_PASSWORD are not configured."""


@dataclass(frozen=True, slots=True)
class SnapshotState:
    in_progress: bool = False
    types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FusionState:
    commit_token: str | None = None
    snapshot: SnapshotState = field(default_factory=SnapshotState)
    updated_at: str | None = None


class FusionClient:
    def __init__(
        self,
        *,
        credentials: FusionCredentials | None = None,
        transport: httpx.BaseTransport | None = None,
        state_dir: Any = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
        housekeeping_delay: float = 600.0,
    ) -> None:
        self._credentials = credentials
        self._state_dir = state_dir if state_dir is not None else FUSION_DIR
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._housekeeping_delay = housekeeping_delay
        self._http = httpx.Client(
            timeout=180.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/xml, text/xml"},
        )

    def __repr__(self) -> str:
        try:
            creds = self._creds
            head = f"client_id={creds.client_id}, base_url={creds.base_url!r}"
        except FusionAPIError:
            head = "client_id=None"
        return f"FusionClient({head}, creds=<set>)"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FusionClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- auth --------------------------------------------------------

    @property
    def _creds(self) -> FusionCredentials:
        if self._credentials is None:
            self._credentials = resolve_fusion_credentials()
        if self._credentials is None:
            raise FusionCredentialsError(
                "FUSION_CLIENT_ID / FUSION_PASSWORD are not set (process env or .env.local)."
            )
        return self._credentials

    def _is_plaintext(self) -> bool:
        return self._creds.base_url.startswith("http://")

    # -- transport --------------------------------------------------

    def _post(self, method: str, *, form: dict[str, str] | None = None) -> Element:
        creds = self._creds
        if self._is_plaintext():
            logger.warning(
                "fusion: base URL is plaintext http:// — credentials digest in the clear"
            )
        url = f"{creds.base_url}/{method}"

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            params = security_params(creds.client_id, creds.password)  # fresh every attempt
            try:
                resp = self._http.post(url, params=params, data=form or None)
            except httpx.TransportError as exc:
                last_error = exc
                self._sleep(attempt)
                continue

            if resp.status_code >= 500:
                last_error = FusionAPIError(f"{method}: HTTP {resp.status_code}")
                logger.warning(
                    "fusion: %s HTTP %s (attempt %d)", method, resp.status_code, attempt + 1
                )
                self._sleep(attempt)
                continue

            try:
                root = fromstring(resp.content)
            except ParseError as exc:
                if resp.status_code >= 400:
                    raise FusionAPIError(
                        f"{method}: HTTP {resp.status_code} {resp.text[:200]!r}"
                    ) from exc
                raise FusionAPIError(f"{method}: unparseable response {resp.text[:200]!r}") from exc

            try:
                raise_for_exception(root)
            except FusionException as exc:
                if exc.type in _TRANSIENT_EXCEPTIONS and attempt + 1 < self._max_retries:
                    last_error = exc
                    delay = self._housekeeping_delay if exc.type == _HOUSEKEEPING else None
                    logger.warning("fusion: %s <Exception type=%s> — retrying", method, exc.type)
                    self._sleep(attempt, override=delay)
                    continue
                raise
            return root

        raise FusionAPIError(f"{method}: retries exhausted ({last_error})")

    def _sleep(self, attempt: int, *, override: float | None = None) -> None:
        time.sleep(override if override is not None else self._retry_base_delay * (2**attempt))

    # -- sync methods ---------------------------------------------

    def request_snapshot(self) -> str | None:
        """``RequestSnapshot`` — pause the queue and re-send every object. Returns any warning."""
        return request_completed_warning(self._post("RequestSnapshot"))

    def request_rollback(self, start_time: str) -> str | None:
        """``RequestRollback`` — re-send history from ``start_time`` (``YYYY-MM-DD-HH-MM-SS``)."""
        return request_completed_warning(
            self._post("RequestRollback", form={"startTime": start_time})
        )

    def request_listing(self, listing_id: str) -> str | None:
        """``RequestListing`` — re-send one listing's CreateOrUpdate (or Delete if gone)."""
        return request_completed_warning(
            self._post("RequestListing", form={"listingId": str(listing_id)})
        )

    def get_changes(self, commit_token: str | None) -> ChangesBatch:
        """``GetChanges`` — acknowledge ``commit_token`` and fetch the next batch.

        Pass ``None`` / empty to re-send the last unacknowledged batch (or start).
        """
        form = {"commitToken": commit_token} if commit_token else None
        return parse_changes(self._post("GetChanges", form=form))

    def get_client_state(self) -> ClientState:
        """``GetClientState`` — the current cursor without consuming events."""
        return parse_client_state(self._post("GetClientState"))

    # -- persisted state ----------------------------------------

    def _state_path(self) -> Any:
        return self._state_dir / "state.json"

    def load_state(self) -> FusionState:
        path = self._state_path()
        if not path.is_file():
            return FusionState()
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return FusionState()
        snap = data.get("snapshot") or {}
        return FusionState(
            commit_token=data.get("commit_token") or None,
            snapshot=SnapshotState(
                in_progress=bool(snap.get("in_progress")),
                types=tuple(snap.get("types") or ()),
            ),
            updated_at=data.get("updated_at"),
        )

    def save_state(self, state: FusionState) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "commit_token": state.commit_token,
                    "snapshot": {
                        "in_progress": state.snapshot.in_progress,
                        "types": list(state.snapshot.types),
                    },
                    "updated_at": state.updated_at,
                }
            )
        )
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def area_tree_path(self) -> Any:
        return self._state_dir / "area_tree.json"

    def developments_path(self) -> Any:
        return self._state_dir / "developments.json"
