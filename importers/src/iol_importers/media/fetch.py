"""Download vendor photos, validate them, and hand them to a :class:`MediaStore`.

A source-URL index (``<root>/.index/<sha256(url)>.json``) records what each vendor
URL resolved to, so a re-poll re-downloads nothing. One photo failing — 404,
timeout, oversize, not an image — is logged and skipped; it never fails the
listing it belongs to.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .sniff import detect
from .store import MediaStore, StoredAsset, UnsupportedMediaError

logger = logging.getLogger("iol_importers.media")

DEFAULT_MAX_BYTES = 15 * 1024 * 1024
_TIMEOUT = 30.0
_INDEX_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR


@dataclass(slots=True)
class FetchStats:
    downloaded: int = 0
    reused: int = 0
    failed: int = 0
    failures: list[str] = field(default_factory=list)


class SourceUrlIndex:
    """Maps a vendor photo URL to the asset it resolved to (survives re-runs)."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.dir = Path(root) / ".index"

    def _path(self, source_url: str) -> Path:
        return self.dir / f"{hashlib.sha256(source_url.encode()).hexdigest()}.json"

    def get(self, source_url: str) -> StoredAsset | None:
        path = self._path(source_url)
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text())
            asset = StoredAsset(
                sha256=row["sha256"],
                path=Path(row["path"]),
                url=row["url"],
                content_type=row["content_type"],
                byte_size=row["byte_size"],
                width_px=row.get("width_px"),
                height_px=row.get("height_px"),
            )
        except (ValueError, OSError, KeyError):
            return None
        # A hit is only real if the stored file is still on disk.
        return asset if asset.path.is_file() else None

    def put(self, source_url: str, asset: StoredAsset) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(source_url)
        path.write_text(
            json.dumps(
                {
                    "sha256": asset.sha256,
                    "path": str(asset.path),
                    "url": asset.url,
                    "content_type": asset.content_type,
                    "byte_size": asset.byte_size,
                    "width_px": asset.width_px,
                    "height_px": asset.height_px,
                }
            )
        )
        os.chmod(path, _INDEX_FILE_MODE)


def _download(http: httpx.Client, url: str, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with http.stream("GET", url, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"exceeds {max_bytes} bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_and_store(
    source_urls: Iterable[str],
    *,
    feed: str,
    store: MediaStore,
    http: httpx.Client,
    index: SourceUrlIndex | None = None,
    refresh: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[list[StoredAsset], FetchStats]:
    """Return ``(assets, stats)`` — assets in input order, failures dropped."""
    stats = FetchStats()
    assets: list[StoredAsset] = []
    seen: set[str] = set()

    for raw_url in source_urls:
        url = (raw_url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)

        if index is not None and not refresh:
            cached = index.get(url)
            if cached is not None:
                assets.append(cached)
                stats.reused += 1
                continue

        try:
            data = _download(http, url, max_bytes=max_bytes)
            if detect(data) is None:
                raise UnsupportedMediaError("response is not a recognised image")
            asset = store.put(data, feed=feed)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            stats.failed += 1
            stats.failures.append(f"{url}: {exc}")
            logger.warning("media: skipped %s (%s)", url, exc)
            continue

        if index is not None:
            index.put(url, asset)
        assets.append(asset)
        stats.downloaded += 1

    return assets, stats
