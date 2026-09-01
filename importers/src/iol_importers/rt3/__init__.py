"""RT3 (Rawson) feed adapter — one bracket-KV file per province at
``https://webservices.rawsonproperties.co.za/iol-{Province}.txt``.

A plain public GET (no auth) per province returns that slice of the agency's book
as the bracketed key-value text format shared by RT3, MyRoof and PropertyPost.
This adapter sits on the shared parser :mod:`iol_importers.bracket_kv` (it does
**not** reimplement it) and feeds records into
:func:`iol_importers.listings.importer.import_listings`.

An agency publishes several province files (which provinces is config on the
``feed_sources`` row); the adapter fetches every configured province, imports them
in one job, and reconciles **per province** with
:func:`iol_importers.lifecycle.withdraw.withdraw_missing` scoped to
``raw_data ->> 'rt3_province'``.

Vendor specifics (confirmed against a real 4,137-record Gauteng run):

* single brand ("Rawson Properties") — ``Branch_ID`` / ``Branch_Name`` are the
  per-listing office identity, used directly as the agency;
* numbered co-agent fields (``Agent_Name``, ``Agent_Name_2``, …) — the first
  agent resolves through Step 14, the full roster goes to ``raw_data.rt3_agents``;
* ``Kitchens`` is an underscore-token list (``_gas hob_, _granite tops_``) —
  unique to RT3, parsed into ``raw_data.rt3_kitchen_fittings``;
* ``Views`` / ``Security`` / ``Balcony`` / ``Patio`` / ``Garden`` are
  comma-separated free-text tag lists folded into ``features``;
* a hyphenated ``Type`` taxonomy (``Commercial - Retail``); ``Guest House`` /
  ``Unclassified`` quarantine rather than guess;
* ``GPS`` zero sentinel is ``"0.00000000,0.00000000"``.
"""

from .adapter import Rt3RunResult, format_result, run
from .client import Rt3APIError, Rt3Client
from .source import Rt3ConfigError, Rt3Source, resolve_source

__all__ = [
    "Rt3RunResult",
    "format_result",
    "run",
    "Rt3Client",
    "Rt3APIError",
    "Rt3ConfigError",
    "Rt3Source",
    "resolve_source",
]
