"""PropertyEngine listing importer — the Gumtree Pro "Real Estate Standard Template
Feed" v1.0.1 schema, which PropertyEngine implements to syndicate listings to us.

The schema doc (``~/Documents/setup-guides/2RealEstate_StandardTemplate_GumtreePro
(1) (2).pdf``) specifies the *file format* only — never a hosting URL, an auth
scheme, or a schedule. Those still need to come from PropertyEngine directly (see
``MAPPING_NOTES.md``).

* The doc says JSON; the only PropertyEngine feed anyone has observed is XML with
  the same field semantics. :mod:`.decode` auto-detects and normalises both.
* :mod:`.locations` is the Appendix A gazetteer (``LocationID`` -> province / area
  / locality / centroid), transcribed once and checked in.
* :mod:`.validate` enforces the doc's value rules (bad date / email / phone /
  ``Type`` / ``Status`` -> ``import_errors`` with ``error_type='validation'``) and
  logs — never rejects — the casing conventions the real feed breaks.
* :mod:`.map` maps a ``Property`` to the Step 14 ``import_listings`` contract.
"""

from .adapter import PropertyEngineRunResult, format_result, run
from .client import PropertyEngineAPIError, PropertyEngineAuthError, PropertyEngineClient

__all__ = [
    "PropertyEngineRunResult",
    "format_result",
    "run",
    "PropertyEngineClient",
    "PropertyEngineAuthError",
    "PropertyEngineAPIError",
]
