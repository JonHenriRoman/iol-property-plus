"""Fusion FeedStore listing importer — Private Property SA's event-sourced XML sync.

Not a REST pull: four POST methods on ``…/v1/sync/`` (``RequestSnapshot``,
``GetChanges``, ``RequestRollback``, ``GetClientState``), each signed with a
fresh SecurityToken (``base64(sha1(f"{timestamp}*{password}*{salt}"))``, never
reused). ``GetChanges`` streams ``<CreateOrUpdate>`` / ``<Delete>`` /
``<Snapshot>`` events wrapping ``<Office>`` / ``<Agent>`` / ``<Listing>`` /
``<Development>`` / ``<AreaTree>``.

* Listings feed :func:`iol_importers.listings.import_listings` (upsert on the
  Fusion id; ``<Delete>`` → ``lifecycle.withdraw_listings`` soft-delete).
* Offices → ``agencies``, Agents → ``agents`` (+ the ``*_vendor_ids`` maps),
  ``<Delete>`` → ``status='Inactive'`` (:mod:`.reference`).
* AreaTree builds ``data/fusion/area_tree.json`` — a ``suburbId`` → name
  crosswalk fed to the existing ``resolve_suburb`` (no parallel geography table).
* Developments are captured to ``data/fusion/developments.json`` + ``raw_data``;
  canonical ``developments`` sync is a flagged follow-up (needs a migration).

The ``commitToken`` is persisted (``data/fusion/state.json``) only after a batch
is fully applied — the doc's "omit the token to replay the last batch" recovery.
"""

from .adapter import FusionRunResult, format_result, run
from .client import FusionAPIError, FusionClient, FusionCredentialsError
from .parse import FusionException

__all__ = [
    "FusionRunResult",
    "format_result",
    "run",
    "FusionClient",
    "FusionAPIError",
    "FusionCredentialsError",
    "FusionException",
]
