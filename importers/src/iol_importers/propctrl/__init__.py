"""PropCtrl Listing Service v1 feed adapter.

Reads the PropCtrl change feed (``/listing/v1/listings/changes``), fetches the
new/modified listings ten at a time, and feeds the ``Active`` ones through
``iol_importers.listings.import_listings``. Read-only: the status write-back half
of the PropCtrl partner protocol (``PUT /listing/v1/listings/{id}``) is
deliberately not implemented — see ``MAPPING_NOTES.md``.
"""

from .adapter import DEFAULT_FROM_DATE, PropctrlRunResult, run
from .client import PropctrlAuthError, PropctrlClient

__all__ = [
    "DEFAULT_FROM_DATE",
    "PropctrlRunResult",
    "run",
    "PropctrlClient",
    "PropctrlAuthError",
]
