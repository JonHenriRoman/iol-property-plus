"""``allsa-import`` — pull one AllSA agency's feed into the DB.

Each agency is its own ``feed_sources`` row (``code='allsa-<agencyid>'``) with the
``agencyid`` in ``auth_config->>'agency_id'``. ``--agency-id`` overrides that for a
one-off run before the row is seeded.

The feed is a full resend (~3.5 MB for a mid-size agency); a nightly pull is the
right cadence, not a short poll:

    # crontab
    15 3 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers allsa-import --feed-source allsa-10173 \\
        >> /var/log/iol/allsa-10173.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import AllsaAPIError
from .parse import AllsaParseError
from .source import AllsaConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="allsa-import", description="Import an AllSA Property agency feed."
    )
    parser.add_argument("--feed-source", default="allsa", help="feed_sources.code (default: allsa)")
    parser.add_argument(
        "--agency-id",
        default=None,
        help="agencyid override — skips the feed_sources.auth_config lookup",
    )
    parser.add_argument("--file", default=None, help="read this local feed file instead of the URL")
    parser.add_argument("--max-listings", type=int, default=None, help="bound listings processed")
    parser.add_argument(
        "--no-reconcile",
        action="store_true",
        help="do not withdraw listings absent from this pull",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch, parse and map only; no database writes"
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            agency_id=args.agency_id,
            file=args.file,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except (AllsaConfigError, AllsaAPIError, AllsaParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
