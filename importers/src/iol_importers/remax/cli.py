"""``remax-import`` — pull RE/MAX listings into the database via the importer.

Auth: AWS SigV4 (`execute-api`, `eu-west-1`) + an `x-api-key` header, every
request. Needs, in .env.local: REMAX_ACCESS_KEY, REMAX_SECRET_KEY, REMAX_API_KEY
(REMAX_API_BASE_URL optional).

Default mode is incremental (resumes from `data/remax/checkpoint.json`).
`--mode full` walks every agent. Deletions from `/lists_deleted` are applied as
soft-deletes on every run unless `--no-deleted`.
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import RemaxAPIError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remax-import",
        description="Import RE/MAX listings (full | incremental) and apply deletions.",
    )
    parser.add_argument("--mode", choices=("incremental", "full"), default="incremental")
    parser.add_argument("--feed-source", default="remax", help="feed_sources.code (default: remax)")
    parser.add_argument(
        "--start-date", default=None, help="ISO timestamp; overrides the checkpoint"
    )
    parser.add_argument("--max-pages", type=int, default=None, help="bound pages per traversal")
    parser.add_argument("--max-agents", type=int, default=None, help="bound agents (full mode)")
    parser.add_argument("--no-deleted", action="store_true", help="skip the /lists_deleted pass")
    parser.add_argument("--deleted-only", action="store_true", help="only run /lists_deleted")
    parser.add_argument(
        "--no-checkpoint", action="store_true", help="do not advance the checkpoint"
    )
    args = parser.parse_args(argv)

    try:
        result = run(
            feed_source_code=args.feed_source,
            mode=args.mode,
            start_date=args.start_date,
            max_pages=args.max_pages,
            max_agents=args.max_agents,
            with_deleted=not args.no_deleted,
            deleted_only=args.deleted_only,
            write_checkpoint=not args.no_checkpoint,
        )
    except RemaxAPIError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
