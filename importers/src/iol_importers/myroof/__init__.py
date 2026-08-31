"""MyRoof feed adapter — the per-franchise bracket-KV feed at
``https://rat.myroof.co.za/{token}``.

One HTTP GET returns a franchise's whole book as the bracketed key-value text
format shared by RT3, MyRoof and PropertyPost. This adapter sits on the shared
parser :mod:`iol_importers.bracket_kv` (it does **not** reimplement it) and feeds
records into :func:`iol_importers.listings.importer.import_listings`.

Full resend, no delta, no delete signal — absences are reconciled with
:func:`iol_importers.lifecycle.withdraw.withdraw_missing`, exactly like the AllSA
and PropertyEngine adapters.

Vendor specifics (confirmed against a real 3,857-record run):

* the whole feed is **bank-repossessed stock** — every record gets a synthetic
  ``Repossession`` feature tag, and ``Agent_Name`` is a lender/program label
  ("Standard Bank Repossessed", …), not a person;
* ``Description`` carries literal ``<p>`` tags as paragraph breaks — stripped, not
  passed through;
* ``GPS`` is one ``"lat,lng"`` string with a bare-comma "not supplied" sentinel;
* single brand — every record is ``Branch_Name`` ``"MyRoof.co.za"`` /
  ``Branch_ID`` ``"1"``; franchise identity is the ``feed_sources`` row itself.
"""

from .adapter import MyroofRunResult, format_result, run
from .client import MyroofAPIError, MyroofClient
from .source import MyroofConfigError, MyroofSource, resolve_source

__all__ = [
    "MyroofRunResult",
    "format_result",
    "run",
    "MyroofClient",
    "MyroofAPIError",
    "MyroofConfigError",
    "MyroofSource",
    "resolve_source",
]
