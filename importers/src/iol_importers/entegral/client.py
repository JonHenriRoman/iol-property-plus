"""Entegral pull-feed client — two Basic-auth GET endpoints.

* ``GET /api/officeslist`` — the offices that opted into syndication to us.
* ``GET /api/listings?type=officelistings&ref=<officereference>`` — one office's
  active listings, agent + office contact inline (a shape similar to the Sync
  API ``CreateOrUpdateListing`` object).

Entegral gave us ``http://`` URLs. Sending Basic credentials in the clear is
avoidable, so the client tries ``https://`` first and drops to ``http://`` only
when TLS is genuinely unreachable, logging a one-line warning when it does.

The Basic credential is built once into a private attribute; ``__repr__`` and
every log line redact it.
"""

from __future__ import annotations

import base64
import json
import logging
import stat
import time
from typing import Any

import httpx

from iol_importers.config import (
    ENTEGRAL_DIR,
    EntegralCredentials,
    resolve_entegral_credentials,
)

logger = logging.getLogger("iol_importers.entegral")

_RETRY_STATUS = frozenset({502, 503, 504})
_OFFICESLIST_PATH = "/officeslist"
_LISTINGS_PATH = "/listings"

# officeslist entries — Entegral said each carries an "officereference"; accept
# the obvious spellings until the live shape is pinned by a probe.
_OFFICE_REF_KEYS = ("officereference", "officeReference", "reference", "ref", "office_ref")
_OFFICE_NAME_KEYS = (
    "officename",
    "officeName",
    "name",
    "office",
    "tradingName",
    "trading_name",
    "displayName",
)


class EntegralAuthError(RuntimeError):
    """The credentials were rejected (HTTP 401) or are not configured."""


class EntegralAPIError(RuntimeError):
    """An Entegral endpoint returned an error status or exhausted retries."""


def office_reference(office: dict[str, Any]) -> str | None:
    for key in _OFFICE_REF_KEYS:
        value = office.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def office_name(office: dict[str, Any]) -> str | None:
    for key in _OFFICE_NAME_KEYS:
        value = office.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


class EntegralClient:
    def __init__(
        self,
        *,
        credentials: EntegralCredentials | None = None,
        transport: httpx.BaseTransport | None = None,
        state_dir: Any = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._credentials = credentials
        self._auth_header: str | None = None
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._state_dir = state_dir if state_dir is not None else ENTEGRAL_DIR
        self._downgraded = False
        self._http = httpx.Client(
            timeout=120.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def __repr__(self) -> str:
        state = "<set>" if self._credentials or self._auth_header else None
        try:
            base = self._creds.base_url
        except EntegralAuthError:
            base = None
        return f"EntegralClient(base_url={base!r}, auth={state})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EntegralClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- auth ---------------------------------------------------------

    @property
    def _creds(self) -> EntegralCredentials:
        if self._credentials is None:
            self._credentials = resolve_entegral_credentials()
        if self._credentials is None:
            raise EntegralAuthError(
                "ENTEGRAL_USERNAME / ENTEGRAL_PASSWORD are not set (process env or .env.local)."
            )
        return self._credentials

    def _headers(self) -> dict[str, str]:
        if self._auth_header is None:
            creds = self._creds
            raw = f"{creds.username}:{creds.password}".encode()
            self._auth_header = "Basic " + base64.b64encode(raw).decode()
        return {"Authorization": self._auth_header}

    def _bases(self) -> list[str]:
        base = self._creds.base_url
        if base.startswith("https://") and not self._downgraded:
            return [base, "http://" + base[len("https://") :]]
        return [base]

    # -- transport --------------------------------------------------

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            for base in self._bases():
                url = f"{base}{path}"
                try:
                    resp = self._http.get(url, params=params, headers=self._headers())
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last_error = exc
                    if base.startswith("https://"):
                        logger.warning(
                            "entegral: TLS unreachable, retrying over http:// (%s)", path
                        )
                        self._downgraded = True
                    continue
                except httpx.TransportError as exc:
                    last_error = exc
                    continue

                if resp.status_code == httpx.codes.UNAUTHORIZED:
                    raise EntegralAuthError("Entegral rejected the credentials (HTTP 401)")
                if resp.status_code in _RETRY_STATUS:
                    last_error = EntegralAPIError(f"{path}: HTTP {resp.status_code}")
                    break
                if resp.status_code >= 400:
                    raise EntegralAPIError(f"{path}: HTTP {resp.status_code} {resp.text[:200]!r}")
                return _parse_json(resp)

            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise EntegralAPIError(f"{path}: retries exhausted ({last_error})")

    # -- endpoints -------------------------------------------------

    def list_offices(self) -> list[dict[str, Any]]:
        """``GET /officeslist`` — the syndicating offices, each with an officereference."""
        return _as_rows(self._get(_OFFICESLIST_PATH), ("offices", "officeslist", "office"))

    def office_listings(self, ref: str) -> list[dict[str, Any]]:
        """``GET /listings?type=officelistings&ref=<ref>`` — one office's active listings."""
        body = self._get(_LISTINGS_PATH, params={"type": "officelistings", "ref": str(ref)})
        return _as_rows(body, ("listings", "listing"))

    # -- checkpoint -----------------------------------------------

    def _last_sync_path(self) -> Any:
        return self._state_dir / "last-sync.json"

    def load_last_sync(self) -> str | None:
        path = self._last_sync_path()
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text()).get("finished_at") or None
        except (ValueError, OSError):
            return None

    def save_last_sync(self, finished_at: str) -> None:
        path = self._last_sync_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"finished_at": finished_at}))
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _parse_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise EntegralAPIError(f"non-JSON response: {resp.text[:200]!r}") from exc


def _as_rows(body: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in keys:
            value = body.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        # a single object under no wrapper
        if any(k in body for k in ("clientPropertyID", *_OFFICE_REF_KEYS)):
            return [body]
    return []
