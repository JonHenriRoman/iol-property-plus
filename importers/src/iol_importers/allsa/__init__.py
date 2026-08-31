"""AllSA Property feed adapter — the ``iol.ashx`` XML feed.

AllSA Property syndicates an agency's whole book as one XML document at
``https://www.allsaproperty.co.za/feeds/iol.ashx?agencyid={agencyid}``. It is a
full resend on every pull — no delta endpoint, no deletion signal, no auth — so
the adapter mirrors :mod:`iol_importers.propertyengine`: fetch, parse, map,
:func:`~iol_importers.listings.importer.import_listings`, then reconcile absences
with :func:`~iol_importers.lifecycle.withdraw.withdraw_missing`.

* The per-agency ``agencyid`` is configuration on the ``feed_sources`` row
  (``auth_config ->> 'agency_id'``), never hardcoded — see :mod:`.source`.
* One agency's feed spans multiple offices; office identity is ``BranchId``
  (:mod:`.reference`), not ``Agency_Location`` (the listing's servicing town).
* ``<Features>`` is a free-form bag whose child set varies per listing and which
  the real feed sometimes repeats hundreds of times over — :mod:`.features`
  parses it by iterating the actual children and de-duplicating.
"""

from .adapter import AllsaRunResult, format_result, run
from .client import AllsaAPIError, AllsaClient
from .parse import AllsaParseError, Property
from .source import AllsaConfigError, AllsaSource, resolve_source

__all__ = [
    "AllsaRunResult",
    "format_result",
    "run",
    "AllsaClient",
    "AllsaAPIError",
    "AllsaParseError",
    "Property",
    "AllsaConfigError",
    "AllsaSource",
    "resolve_source",
]
