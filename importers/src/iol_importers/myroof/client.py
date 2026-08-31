"""MyRoof feed client — one HTTP GET of ``{base_url}/{token}``, or a file off disk.

The opaque token in the URL path is the entire credential (no auth header). It is
**never** put in ``__repr__``, a log line, or an exception message — errors name
the HTTP status and the caller's ``feed_source_code`` only.

A response that is not 2xx, or whose body does not contain ``[[Listing_Start]]``
near the top (an HTML error page, an empty body), raises :class:`MyroofAPIError`
rather than being handed to the parser — so a broken fetch cannot make the
downstream ``withdraw_missing`` reconcile the whole book to zero.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

from iol_importers.config import resolve_myroof_base_url

logger = logging.getLogger("iol_importers.myroof")

_RETRY_STATUS = frozenset({500, 502, 503, 504})
_SNIFF_BYTES = 4096


class MyroofAPIError(RuntimeError):
    """The feed host returned an error, a non-feed body, or retries were exhausted."""


def _looks_like_feed(body: bytes) -> bool:
    return b"[[Listing_Start]]" in body[:_SNIFF_BYTES]


class MyroofClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._base_url = (base_url or resolve_myroof_base_url()).strip().rstrip("/")
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._http = httpx.Client(
            timeout=180.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "text/plain, */*"},
        )

    def __repr__(self) -> str:
        return f"MyroofClient(base_url={self._base_url!r})"  # never the token

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MyroofClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_file(self, path: str | Path) -> bytes:
        """Read a local feed file. No network."""
        return Path(path).read_bytes()

    def fetch(self, token: str) -> bytes:
        """GET ``{base_url}/{token}``. Returns the raw bracket-KV body.

        The token is not echoed into any error text — a bad token surfaces as a
        plain ``HTTP 404`` (or a non-feed body).
        """
        url = f"{self._base_url}/{token}"
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(url)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in _RETRY_STATUS:
                    last_error = MyroofAPIError(f"feed: HTTP {resp.status_code}")
                elif resp.status_code >= 400:
                    raise MyroofAPIError(
                        f"feed: HTTP {resp.status_code} — check the franchise token"
                    )
                elif not _looks_like_feed(resp.content):
                    raise MyroofAPIError(
                        "feed body is not bracket-KV text (no [[Listing_Start]] near "
                        f"the top; HTTP {resp.status_code}, "
                        f"content-type {resp.headers.get('content-type', '')!r})"
                    )
                else:
                    return resp.content
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise MyroofAPIError(f"feed: retries exhausted ({last_error})")
