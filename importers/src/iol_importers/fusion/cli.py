"""``fusion-import`` — drain the Fusion FeedStore sync queue into the database.

Auth: a fresh SecurityToken per call. Needs, in .env.local: FUSION_CLIENT_ID,
FUSION_PASSWORD (FUSION_API_BASE_URL optional — point it at the doc's QA host for
testing; production otherwise).

First run for a client (no ``data/fusion/state.json``) issues ``RequestSnapshot``
and drains the resulting snapshot across however many ``GetChanges`` calls it
takes. Subsequent runs resume from the saved ``commitToken``. ``NotifyChangesAvailable``
(Fusion calling into us) is out of scope — see MAPPING_NOTES.

Scheduling (nothing in this repo wires it — see the root README's "Not yet
implemented"). Poll every ~15 minutes, or drive it from the notification webhook
once that half is built:

    # crontab
    */15 * * * *  cd /srv/iol-property-plus && \\
        uv run --project importers fusion-import >> /var/log/iol/fusion.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from .adapter import format_result, run
from .client import FusionAPIError, FusionClient
from .parse import FusionException


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fusion-import",
        description="Drain the Fusion FeedStore sync queue (snapshot + GetChanges).",
    )
    parser.add_argument(
        "--feed-source", default="fusion", help="feed_sources.code (default: fusion)"
    )
    parser.add_argument(
        "--max-batches", type=int, default=None, help="stop after N GetChanges batches"
    )
    parser.add_argument(
        "--force-snapshot", action="store_true", help="issue RequestSnapshot before draining"
    )
    parser.add_argument(
        "--rollback",
        metavar="YYYY-MM-DD-HH-MM-SS",
        default=None,
        help="issue RequestRollback from this UTC time, then drain",
    )
    parser.add_argument(
        "--request-listing",
        metavar="ID",
        default=None,
        help="issue RequestListing for one id, then drain",
    )
    parser.add_argument(
        "--state", action="store_true", help="print local state + GetClientState, then exit"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="drain + map only; no DB writes, no token persist"
    )
    parser.add_argument(
        "--no-state", action="store_true", help="do not persist the commitToken / crosswalk"
    )
    args = parser.parse_args(argv)

    try:
        with FusionClient() as client:
            if args.state:
                _print_state(client)
                return 0
            if args.rollback:
                warning = client.request_rollback(args.rollback)
                print(f"RequestRollback: {warning or 'ok'}")
            if args.request_listing:
                warning = client.request_listing(args.request_listing)
                print(f"RequestListing: {warning or 'ok'}")
            result = run(
                feed_source_code=args.feed_source,
                max_batches=args.max_batches,
                force_snapshot=args.force_snapshot,
                dry_run=args.dry_run,
                write_state=not args.no_state,
                client=client,
            )
    except (FusionAPIError, FusionException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(format_result(result))
    return 0


def _print_state(client: FusionClient) -> None:
    state = client.load_state()
    print(f"local commit_token : {state.commit_token or '(none)'}")
    print(f"snapshot in progress: {state.snapshot.in_progress}  types={list(state.snapshot.types)}")
    try:
        remote = client.get_client_state()
        print(
            f"remote             : name={remote.name} type={remote.type} "
            f"commit_token={remote.commit_token} totalSyncEvents={remote.total_sync_events} "
            f"lastSequenceId={remote.last_sync_event_sequence_id}"
        )
    except (FusionAPIError, FusionException) as exc:
        print(f"remote             : unavailable ({exc})")


if __name__ == "__main__":
    raise SystemExit(main())
