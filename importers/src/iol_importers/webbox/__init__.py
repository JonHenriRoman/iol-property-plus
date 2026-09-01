"""Webbox feed adapter — the per-site XML feed at
``{domain}/template/feeds,WebboxFeedForSite.vm/siteid/{siteid}/securitykey/{securitykey}/feed.xml``.

A plain GET (the URL itself is the credential) returns one site's whole book as
clean lowercase-tag XML. This adapter stream-parses it with
``xml.etree.ElementTree.iterparse`` (stdlib — no lxml) and feeds records into
:func:`iol_importers.listings.importer.import_listings`.

Full resend, no delta, no delete signal — absences are reconciled with
:func:`iol_importers.lifecycle.withdraw.withdraw_missing`, and rich agency/agent
contact data is enriched through :mod:`iol_importers.webbox.reference` before the
import, exactly like the AllSA adapter.

Structural note: the repeated ``<property>`` nests two levels inside ``<agency>``,
beside that agency's ``<agency-details>``. The parser carries the agency context
down onto each flat record and reports which outer form the feed actually used
(``wrapped`` / ``bare-property`` / ``streamed``) on the run result.

Vendor specifics (confirmed against production captures of 21 and 411 properties):

* ``listing-type`` (``Sale`` / ``Rent``) is the listing type — no lifecycle field;
* ``price/currency`` must be ``ZAR`` (Step 14 has no per-listing currency column) —
  a non-ZAR listing is rejected; ``location/country`` is validated, not hardcoded;
* an empty ``<amount/>`` is a real price-on-application case;
* ``<features>`` is a free-form bag (``bedrooms``/``bathrooms``/``garages``/
  ``taxes`` → columns, the rest captured);
* ``land-size`` / ``property-size`` carry a vendor unit string
  (``meters_squared``, ``hectares``) → ``erf_size`` / ``floor_size``;
* multiple ``<agent>`` — the first drives the FK, the full roster → ``raw_data``;
* no date field of any kind → ``listed_at`` NULL.
"""

from .adapter import WebboxRunResult, format_result, run
from .client import WebboxAPIError, WebboxClient
from .parse import ParseResult, Property, WebboxParseError, parse_feed
from .source import WebboxConfigError, WebboxSource, resolve_source

__all__ = [
    "WebboxRunResult",
    "format_result",
    "run",
    "WebboxClient",
    "WebboxAPIError",
    "WebboxParseError",
    "ParseResult",
    "Property",
    "parse_feed",
    "WebboxConfigError",
    "WebboxSource",
    "resolve_source",
]
