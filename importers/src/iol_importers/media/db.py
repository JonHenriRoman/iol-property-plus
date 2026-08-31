"""Keep a listing's ``listing_media`` rows in step with a set of stored assets.

Runs inside the caller's transaction (takes a cursor, not a connection): the
media sync commits or rolls back with the listing upsert that triggered it.
Rows whose ``url`` is no longer in the set are pruned — a photo removed
vendor-side disappears here too.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from .store import StoredAsset

_UPSERT = """
    INSERT INTO listing_media
        (listing_id, media_type, url, caption, display_order, width_px, height_px)
    VALUES (%(listing_id)s, %(media_type)s, %(url)s, %(caption)s,
            %(display_order)s, %(width_px)s, %(height_px)s)
    ON CONFLICT (listing_id, url) DO UPDATE SET
        display_order = EXCLUDED.display_order,
        caption       = COALESCE(EXCLUDED.caption, listing_media.caption),
        width_px      = COALESCE(EXCLUDED.width_px, listing_media.width_px),
        height_px     = COALESCE(EXCLUDED.height_px, listing_media.height_px)
    RETURNING (xmax = 0) AS inserted
"""

_PRUNE = """
    DELETE FROM listing_media
    WHERE listing_id = %(listing_id)s
      AND media_type = %(media_type)s
      AND NOT (url = ANY(%(urls)s))
"""


@dataclass(frozen=True, slots=True)
class MediaSyncResult:
    inserted: int
    updated: int
    pruned: int


def sync_listing_media(
    cur: psycopg.Cursor,
    listing_id: str,
    assets: Sequence[StoredAsset],
    *,
    media_type: str = "Photo",
    captions: Sequence[str | None] | None = None,
) -> MediaSyncResult:
    inserted = updated = 0
    urls: list[str] = []
    for order, asset in enumerate(assets):
        caption = captions[order] if captions and order < len(captions) else None
        cur.execute(
            _UPSERT,
            {
                "listing_id": listing_id,
                "media_type": media_type,
                "url": asset.url,
                "caption": caption,
                "display_order": order,
                "width_px": asset.width_px,
                "height_px": asset.height_px,
            },
        )
        if cur.fetchone()["inserted"]:
            inserted += 1
        else:
            updated += 1
        urls.append(asset.url)

    cur.execute(_PRUNE, {"listing_id": listing_id, "media_type": media_type, "urls": urls})
    pruned = cur.rowcount

    return MediaSyncResult(inserted=inserted, updated=updated, pruned=pruned)
