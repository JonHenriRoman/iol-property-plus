"""Propdata feed adapter.

Authenticates to the Propdata API (HTTP Basic -> per-client bearer token, renewed
rather than re-authenticated), pulls the four listing categories with full
pagination, and feeds each record through ``iol_importers.listings.import_listings``.
"""

from .adapter import CATEGORIES, run
from .client import PropdataAuthError, PropdataClient

__all__ = ["CATEGORIES", "run", "PropdataClient", "PropdataAuthError"]
