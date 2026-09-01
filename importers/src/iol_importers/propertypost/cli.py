"""``propertypost-import`` — pull one PropertyPost agency's feed into the DB.

Each agency is its own ``feed_sources`` row (``code='propertypost-<agency>'``) with
the full static feed URL in ``base_url``. ``--feed-url`` overrides that for a
one-off run before the row is seeded.

The feed is a full resend of the agency's whole book; a nightly pull is the right
cadence:

    # crontab
    30 3 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers propertypost-import --feed-source propertypost-bst \\
        >> /var/log/iol/propertypost-bst.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import PropertypostAPIError
from .source import PropertypostConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="propertypost-import", description="Import a PropertyPost agency feed."
    )
    parser.add_argument(
        "--feed-source", default="propertypost", help="feed_sources.code (default: propertypost)"
    )
    parser.add_argument(
        "--feed-url",
        default=None,
        help="feed URL override — skips the feed_sources.base_url lookup",
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
            feed_url=args.feed_url,
            file=args.file,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except (PropertypostConfigError, PropertypostAPIError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
