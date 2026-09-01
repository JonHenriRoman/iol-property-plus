"""PropertyPost feed client — one HTTP GET of the agency's static URL, or a file
off disk.

There is no credential: the URL is public and served plain. The vendor redirects
plain HTTP to HTTPS (the client follows it) and has been observed returning
``429 Too Many Requests`` under repeated fetching, so ``429`` is retried with
backoff alongside the 5xx statuses.

A response that is not 2xx, or whose body does not contain ``[[Listing_Start]]``
near the top (an HTML error page, an empty body), raises
:class:`PropertypostAPIError` rather than being handed to the parser — so a
broken fetch cannot make the downstream ``withdraw_missing`` reconcile the whole
book to zero.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("iol_importers.propertypost")

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_SNIFF_BYTES = 4096


class PropertypostAPIError(RuntimeError):
    """The feed host returned an error, a non-feed body, or retries were exhausted."""


def _looks_like_feed(body: bytes) -> bool:
    return b"[[Listing_Start]]" in body[:_SNIFF_BYTES]


class PropertypostClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
        retry_base_delay: float = 1.0,
    ) -> None:
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._http = httpx.Client(
            timeout=180.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "text/plain, */*"},
        )

    def __repr__(self) -> str:
        return "PropertypostClient()"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PropertypostClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_file(self, path: str | Path) -> bytes:
        """Read a local feed file. No network."""
        return Path(path).read_bytes()

    def fetch(self, url: str) -> bytes:
        """GET ``url`` (following the vendor's HTTP -> HTTPS redirect). Returns the
        raw bracket-KV body."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(url)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in _RETRY_STATUS:
                    detail = " (rate limited)" if resp.status_code == 429 else ""
                    last_error = PropertypostAPIError(f"feed: HTTP {resp.status_code}{detail}")
                elif resp.status_code >= 400:
                    raise PropertypostAPIError(
                        f"feed: HTTP {resp.status_code} — check the agency feed URL"
                    )
                elif not _looks_like_feed(resp.content):
                    raise PropertypostAPIError(
                        "feed body is not bracket-KV text (no [[Listing_Start]] near "
                        f"the top; HTTP {resp.status_code}, "
                        f"content-type {resp.headers.get('content-type', '')!r})"
                    )
                else:
                    return resp.content
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise PropertypostAPIError(f"feed: retries exhausted ({last_error})")
