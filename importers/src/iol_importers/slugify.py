"""ASCII slug derivation for city and suburb slugs (both NOT NULL, absent from the feed)."""

from __future__ import annotations

import re
import unicodedata

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_DASHES = re.compile(r"-{2,}")


def slugify(value: str) -> str:
    """Lowercase ASCII slug: "Aberdeen Lotusville" -> "aberdeen-lotusville"."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_only.lower())
    slug = _DASHES.sub("-", slug).strip("-")
    return slug
