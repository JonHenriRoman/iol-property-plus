"""PropertyPost feed adapter — one static per-agency URL (e.g.
``http://lms.propertypost.co.za/BstProperties.txt``).

A plain HTTP GET (redirecting to HTTPS), no auth of any kind, returns the
agency's whole book as the bracketed key-value text format shared by RT3, MyRoof
and PropertyPost. This adapter sits on the shared parser
:mod:`iol_importers.bracket_kv` (it does **not** reimplement it) and feeds records
into :func:`iol_importers.listings.importer.import_listings`.

Full resend, no delta, no delete signal — absences are reconciled with
:func:`iol_importers.lifecycle.withdraw.withdraw_missing`, exactly like the AllSA,
PropertyEngine and MyRoof adapters.

Vendor specifics (confirmed against a real 197-record fetch):

* one file carries **both ``For Sale`` and ``To Let``** — there is no separate
  rental endpoint;
* the sampled URL is **one independent agency** (``Branch_ID`` ``39350`` on every
  record) — but agency identity is resolved per record, so a multi-branch file
  needs no code change;
* ``Beds``/``Baths`` duplicate ``Bedrooms``/``Bathrooms`` — coalesced, never
  double-counted;
* ``GPS`` is simply absent when there are no coordinates — no sentinel;
* ``Features_Description`` is unstructured prose — kept verbatim in ``raw_data``,
  never parsed;
* ``Admin_ID`` is a constant company contact, distinct from the per-listing agent.
"""

from .adapter import PropertypostRunResult, format_result, run
from .client import PropertypostAPIError, PropertypostClient
from .source import PropertypostConfigError, PropertypostSource, resolve_source

__all__ = [
    "PropertypostRunResult",
    "format_result",
    "run",
    "PropertypostClient",
    "PropertypostAPIError",
    "PropertypostConfigError",
    "PropertypostSource",
    "resolve_source",
]
