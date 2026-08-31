"""Shared listing-media layer — download a vendor's photos, content-address them
on our own storage, and keep ``listing_media`` rows in sync.

Built for the Entegral feed (its terms forbid hotlinking their images), but
nothing here is Entegral-specific: any feed can adopt it. The store is a plain
content-addressed directory tree under ``data/media/`` served by the Next.js
route handler at ``src/app/media/[...path]/route.ts``; no object storage, no new
dependencies.
"""

from .db import MediaSyncResult, sync_listing_media
from .fetch import FetchStats, SourceUrlIndex, fetch_and_store
from .sniff import detect, dimensions
from .store import MediaStore, StoredAsset

__all__ = [
    "MediaStore",
    "StoredAsset",
    "detect",
    "dimensions",
    "SourceUrlIndex",
    "FetchStats",
    "fetch_and_store",
    "MediaSyncResult",
    "sync_listing_media",
]
