"""A content-addressed local media store.

Files land at ``<root>/<feed>/<sha[:2]>/<sha>.<ext>``; the public URL mirrors the
path under ``url_prefix`` (default ``/media``). Because the key is the SHA-256 of
the bytes, identical images are stored once and re-importing a listing produces
the same URL — ``listing_media``'s ``UNIQUE (listing_id, url)`` absorbs the repeat.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .sniff import detect, dimensions

_DIR_MODE = 0o755
_FILE_MODE = 0o644


class UnsupportedMediaError(ValueError):
    """The bytes are not a JPEG / PNG / WebP / GIF (by magic bytes)."""


@dataclass(frozen=True, slots=True)
class StoredAsset:
    sha256: str
    path: Path
    url: str
    content_type: str
    byte_size: int
    width_px: int | None
    height_px: int | None


class MediaStore:
    def __init__(self, root: str | os.PathLike[str], *, url_prefix: str = "/media") -> None:
        self.root = Path(root)
        self.url_prefix = "/" + url_prefix.strip("/")

    def __repr__(self) -> str:
        return f"MediaStore(root={str(self.root)!r}, url_prefix={self.url_prefix!r})"

    def put(self, data: bytes, *, feed: str) -> StoredAsset:
        """Store ``data`` (already validated as an image) and return its asset."""
        kind = detect(data)
        if kind is None:
            raise UnsupportedMediaError("not a recognised image (JPEG / PNG / WebP / GIF)")
        content_type, ext = kind

        sha = hashlib.sha256(data).hexdigest()
        rel = f"{feed}/{sha[:2]}/{sha}.{ext}"
        target = self.root / rel

        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            self._chmod_dirs(target.parent)
            tmp = target.with_name(f".{sha}.{os.getpid()}.tmp")
            tmp.write_bytes(data)
            os.chmod(tmp, _FILE_MODE)
            os.replace(tmp, target)

        size = dimensions(data, content_type)
        return StoredAsset(
            sha256=sha,
            path=target,
            url=f"{self.url_prefix}/{rel}",
            content_type=content_type,
            byte_size=len(data),
            width_px=size[0] if size else None,
            height_px=size[1] if size else None,
        )

    def _chmod_dirs(self, leaf: Path) -> None:
        for parent in (leaf, leaf.parent):
            try:
                if parent.is_relative_to(self.root) and parent != self.root:
                    os.chmod(parent, _DIR_MODE)
            except OSError:
                pass
