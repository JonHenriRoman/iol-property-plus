"""``propertyengine-import`` — pull the Gumtree Pro standard-template feed into the DB.

The feed is one full-resend file (JSON or XML — the adapter auto-detects). Source:

* ``--file PATH`` — read a local feed file, no network. The primary mode until
  PropertyEngine gives us a URL.
* default — GET ``PROPERTYENGINE_FEED_URL`` (still blank; see ``.env.example``),
  attaching ``Authorization`` only if ``PROPERTYENGINE_FEED_AUTH_TOKEN`` is set.

Scheduling is not wired (see the root README's "Not yet implemented"). PropertyEngine
has not told us how often the file regenerates; a nightly pull is the safe default:

    # crontab
    30 2 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers propertyengine-import >> /var/log/iol/propertyengine.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import PropertyEngineAuthError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="propertyengine-import",
        description="Import the PropertyEngine (Gumtree Pro standard template) feed.",
    )
    parser.add_argument(
        "--feed-source",
        default="propertyengine",
        help="feed_sources.code (default: propertyengine)",
    )
    parser.add_argument("--file", default=None, help="read this local feed file instead of the URL")
    parser.add_argument("--max-listings", type=int, default=None, help="bound listings processed")
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="do not withdraw listings absent from this feed file",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch, decode and map only; no database writes"
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            file=args.file,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except PropertyEngineAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
