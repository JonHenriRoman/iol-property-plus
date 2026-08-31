"""Entegral listing importer — a pull feed, not the push Sync API in the docs.

Confirmed with Entegral (Dillon Gray, 2026-08-13): two HTTP Basic-auth GET
endpoints on ``sync.entegral.net`` — ``/api/officeslist`` lists the offices that
opted into syndication to us, and ``/api/listings?type=officelistings&ref=<ref>``
returns each office's active listings and agent details. Listings feed the Domain
4 importer; disappearance is handled by per-office reconciliation
(:func:`iol_importers.lifecycle.withdraw_missing`); photos are downloaded and
re-hosted on our own storage (:mod:`iol_importers.media`) because Entegral's terms
forbid hotlinking their images.
"""

from .adapter import EntegralRunResult, format_result, run
from .client import EntegralAuthError, EntegralClient

__all__ = [
    "EntegralRunResult",
    "format_result",
    "run",
    "EntegralClient",
    "EntegralAuthError",
]
