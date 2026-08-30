"""``propdata-import`` — pull Propdata listings into the database via the importer.

Auth: HTTP Basic login returns one bearer token per client; the token is renewed
(not re-fetched with Basic auth) on subsequent runs and stored, mode 0600, under
``data/propdata/``. Never logged.

Needs, in .env.local: PROP_DATA_API_USERNAME, PROP_DATA_API_PASSWORD
(PROP_DATA_API_LOGIN_URL optional). Pick the client site with --site or
PROP_DATA_API_SITE.
"""

from __future__ import annotations

import argparse
import os
import sys

from .adapter import CATEGORIES, format_counts, run
from .client import PropdataAuthError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="propdata-import",
        description="Import Propdata residential/commercial/holiday/projects listings.",
    )
    parser.add_argument(
        "--site",
        default=os.environ.get("PROP_DATA_API_SITE"),
        help="Propdata client site domain (or PROP_DATA_API_SITE)",
    )
    parser.add_argument(
        "--feed-source",
        default="propdata",
        help="feed_sources.code to attribute the import to (default: propdata)",
    )
    parser.add_argument(
        "--category",
        action="append",
        choices=CATEGORIES,
        help="limit to one category (repeatable); default: all four",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=None,
        help="stop after N pages per category (for a bounded sample run)",
    )
    args = parser.parse_args(argv)

    if not args.site:
        print("ERROR: --site or PROP_DATA_API_SITE is required", file=sys.stderr)
        return 2

    try:
        results = run(
            site_domain=args.site,
            feed_source_code=args.feed_source,
            categories=tuple(args.category) if args.category else CATEGORIES,
            page_limit=args.page_limit,
        )
    except PropdataAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_counts(results))
    return 0
