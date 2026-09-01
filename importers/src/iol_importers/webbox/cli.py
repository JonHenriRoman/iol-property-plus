"""``webbox-import`` — pull one Webbox site's feed into the DB.

Each site is its own ``feed_sources`` row (``code='webbox-<agency>'``) with the
domain in ``base_url`` and ``siteid`` + ``securitykey`` in ``auth_config``.
``--siteid`` + ``--securitykey`` (+ ``--base-url``) override that for a one-off
run before the row is seeded.

The feed is a full resend of the site's whole book; a nightly pull is the right
cadence:

    # crontab
    50 3 * * *  cd /srv/iol-property-plus && \\
        uv run --project importers webbox-import --feed-source webbox-valuables \\
        >> /var/log/iol/webbox-valuables.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import WebboxAPIError
from .parse import WebboxParseError
from .source import WebboxConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webbox-import", description="Import a Webbox site feed.")
    parser.add_argument(
        "--feed-source", default="webbox", help="feed_sources.code (default: webbox)"
    )
    parser.add_argument("--siteid", default=None, help="siteid override (with --securitykey)")
    parser.add_argument("--securitykey", default=None, help="securitykey override (with --siteid)")
    parser.add_argument("--base-url", default=None, help="site domain override (with --siteid)")
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
            siteid=args.siteid,
            securitykey=args.securitykey,
            base_url=args.base_url,
            file=args.file,
            max_listings=args.max_listings,
            reconcile=not args.no_reconcile,
            dry_run=args.dry_run,
        )
    except (WebboxConfigError, WebboxAPIError, WebboxParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
