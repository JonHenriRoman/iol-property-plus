"""RT3 (Rawson) feed client — one HTTP GET per province file, or a file off disk.

The province files are large (~17 MB each) plain-text bracket-KV, served over a
public URL with no auth of any kind.

A response that is not 2xx, or whose body does not contain ``[[Listing_Start]]``
near the top (an HTML error page, an empty body), raises :class:`Rt3APIError`
rather than being handed to the parser — so a broken fetch of one province cannot
make the downstream per-province ``withdraw_missing`` reconcile that province to
zero.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger("iol_importers.rt3")

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_SNIFF_BYTES = 4096


class Rt3APIError(RuntimeError):
    """The feed host returned an error, a non-feed body, or retries were exhausted."""


def _looks_like_feed(body: bytes) -> bool:
    return b"[[Listing_Start]]" in body[:_SNIFF_BYTES]


class Rt3Client:
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
            timeout=300.0,
            follow_redirects=True,
            transport=transport,
            headers={"Accept": "text/plain, */*"},
        )

    def __repr__(self) -> str:
        return "Rt3Client()"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Rt3Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read_file(self, path: str | Path) -> bytes:
        """Read a local province feed file. No network."""
        return Path(path).read_bytes()

    def fetch(self, province_url: str) -> bytes:
        """GET one province file. Returns the raw bracket-KV body."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = self._http.get(province_url)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if resp.status_code in _RETRY_STATUS:
                    detail = " (rate limited)" if resp.status_code == 429 else ""
                    last_error = Rt3APIError(f"feed: HTTP {resp.status_code}{detail}")
                elif resp.status_code >= 400:
                    raise Rt3APIError(
                        f"feed: HTTP {resp.status_code} for {province_url} "
                        "— check the province token"
                    )
                elif not _looks_like_feed(resp.content):
                    raise Rt3APIError(
                        f"feed body from {province_url} is not bracket-KV text "
                        f"(no [[Listing_Start]] near the top; HTTP {resp.status_code}, "
                        f"content-type {resp.headers.get('content-type', '')!r})"
                    )
                else:
                    return resp.content
            if attempt + 1 < self._max_retries:
                time.sleep(self._retry_base_delay * (2**attempt))
        raise Rt3APIError(f"feed: retries exhausted for {province_url} ({last_error})")
