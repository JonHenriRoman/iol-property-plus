"""Core listing importer — canonical-database-design.md Domain 4.

Takes already-parsed vendor records (plain dicts), normalises ``listing_type``,
resolves every foreign key, upserts on ``(feed_source_id, vendor_listing_id)`` and
routes bad records to ``import_errors`` without stopping the batch. No
vendor-specific feed parsing lives here.
"""

from .importer import import_listings
from .normalize import normalize_listing_type
from .resolve import MappingError

__all__ = ["import_listings", "normalize_listing_type", "MappingError"]
