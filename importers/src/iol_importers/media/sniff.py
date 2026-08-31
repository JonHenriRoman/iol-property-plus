"""Identify an image from its magic bytes and read its pixel dimensions.

The vendor's ``Content-Type`` header is not trusted — the sniffed type decides
both the stored extension and whether the bytes are accepted at all. Dimensions
are best-effort: ``None`` when the header can't be parsed, and the caller stores
NULL rather than guessing. Stdlib only (no Pillow), matching the importers'
"no new tooling" rule.
"""

from __future__ import annotations

import struct

# content_type -> stored file extension (no dot).
_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def detect(data: bytes) -> tuple[str, str] | None:
    """``(content_type, extension)`` from the leading bytes, or ``None``."""
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    return None


def extension_for(content_type: str) -> str | None:
    return _EXT_BY_TYPE.get(content_type)


def dimensions(data: bytes, content_type: str) -> tuple[int, int] | None:
    """``(width_px, height_px)`` read from the file header, or ``None``."""
    try:
        if content_type == "image/png":
            return _png(data)
        if content_type == "image/gif":
            return _gif(data)
        if content_type == "image/jpeg":
            return _jpeg(data)
        if content_type == "image/webp":
            return _webp(data)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _png(data: bytes) -> tuple[int, int] | None:
    # IHDR is always the first chunk: 8-byte sig, 4-byte length, "IHDR", w, h.
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def _gif(data: bytes) -> tuple[int, int] | None:
    width, height = struct.unpack("<HH", data[6:10])
    return int(width), int(height)


def _jpeg(data: bytes) -> tuple[int, int] | None:
    # Walk the marker segments to the first Start-Of-Frame (SOF0..SOF15,
    # excluding the non-frame markers C4/C8/CC).
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return int(width), int(height)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        segment_length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        i += 2 + segment_length
    return None


def _webp(data: bytes) -> tuple[int, int] | None:
    fourcc = data[12:16]
    if fourcc == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return int(width & 0x3FFF), int(height & 0x3FFF)
    if fourcc == b"VP8L":
        bits = struct.unpack("<I", data[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return int(width), int(height)
    if fourcc == b"VP8X":
        w = data[24] | (data[25] << 8) | (data[26] << 16)
        h = data[27] | (data[28] << 8) | (data[29] << 16)
        return int(w + 1), int(h + 1)
    return None
