"""RE/MAX of Southern Africa feed adapter.

Authenticates with AWS SigV4 (`execute-api`, `eu-west-1`) plus an `x-api-key`
header, reads the RE/MAX feed's three sync paths (full via `/agents-page`,
incremental via `/lists-pagenate`, deletions via `/lists_deleted`), and feeds the
listings through `iol_importers.listings.import_listings`. Deletions are
soft-deletes (`status='Withdrawn'`), never row removals.
"""

from .adapter import DEFAULT_START_DATE, RemaxRunResult, run
from .client import RemaxAPIError, RemaxClient, RemaxCredentialsError

__all__ = [
    "DEFAULT_START_DATE",
    "RemaxRunResult",
    "run",
    "RemaxClient",
    "RemaxAPIError",
    "RemaxCredentialsError",
]
