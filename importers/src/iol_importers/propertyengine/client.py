"""PropertyEngine feed client — fetch one file over HTTP, or read one off disk.

The Gumtree Pro schema doc specifies the file format only. Its whole delivery
clause is: "Host the .json file at a publicly accessible URL. Authorization may
be implemented." So:

* the URL comes from ``PROPERTYENGINE_FEED_URL`` (still blank pending
  PropertyEngine — see ``.env.example``);
* ``Authorization`` is attached **only** when ``PROPERTYENGINE_FEED_AUTH_TOKEN``
  is set, as ``Bearer <token>`` (default) or ``Basic <token>`` per
  ``PROPERTYENGINE_FEED_AUTH_SCHEME``;
* ``--file`` reads a local feed file and never touches the network — the primary
  way to exercise the adapter until the real URL lands.

The observed feed URL 302-redirects to a storage object, so ``follow_redirects``
is load-bearing. Transient 5xx are retried with exponential backoff. The token is
redacted from ``__repr__`` and never logged.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from iol_importers.config import PropertyengineFeed, resolve_propertyengine_feed

logger = logging.getLogger("iol_importers.propertyengine")

_RETRY_STATUS = frozenset({502, 503, 504})


class PropertyEngineAuthError(RuntimeError):
    """The feed URL is not configured, or the host rejected the credentials (401/403)."""


class PropertyEngineAPIError(RuntimeError):
    """The feed host returned an error status or retries were exhausted."""


class PropertyEngineClient:
    def __init__(
        self,
        *,
        feed: PropertyengineFeed | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._feed = feed
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._http = httpx.Client(
            timeout=120.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "application/json, application/xml;q=0.9, */*;q=0.1"},
        )

    def __repr__(self) -> str:
        try:
            feed = self._resolved
            url = feed.feed_url
            auth = f"<{feed.auth_scheme}>" if feed.auth_token else None
        except PropertyEngineAuthError:
            url = auth = None
        return f"PropertyEngineClient(feed_url={url!r}, auth={auth})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PropertyEngineClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- config -------------------------------------------------------

    @property
    def _resolved(self) -> PropertyengineFeed:
        if self._feed is None:
            self._feed = resolve_propertyengine_feed()
        if self._feed is None:
            raise PropertyEngineAuthError(
                "PROPERTYENGINE_FEED_URL is not set (process env or .env.local). The "
                "URL is still pending from PropertyEngine; use --file to run against a "
                "local feed file in the meantime."
            )
        return self._feed

    def _headers(self) -> dict[str, str]:
        feed = self._resolved
        if not feed.auth_token:
            return {}
        prefix = "Bearer" if feed.auth_scheme == "bearer" else "Basic"
        return {"Authorization": f"{prefix} {feed.auth_token}"}

    # -- sources -----------------------------------------------------

    def read_file(self, path: str | Path) -> bytes:
        """Read a local feed file. No network, no auth."""
        return Path(path).read_bytes()

    def fetch(self) -> tuple[bytes, str | None]:
        """GET the feed file. Returns ``(body, content_type)``."""
        feed = self._resolved
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(feed.feed_url, headers=self._headers())
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in (401, 403):
                    raise PropertyEngineAuthError(
                        f"PropertyEngine feed host rejected the request (HTTP "
                        f"{resp.status_code}) — check PROPERTYENGINE_FEED_AUTH_TOKEN"
                    )
                if resp.status_code in _RETRY_STATUS:
                    last_error = PropertyEngineAPIError(f"feed: HTTP {resp.status_code}")
                elif resp.status_code >= 400:
                    raise PropertyEngineAPIError(
                        f"feed: HTTP {resp.status_code} {resp.text[:200]!r}"
                    )
                else:
                    return resp.content, resp.headers.get("content-type")
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise PropertyEngineAPIError(f"feed: retries exhausted ({last_error})")
