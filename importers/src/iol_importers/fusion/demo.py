"""Sample run — the Fusion snapshot + delta story, round-tripped through the
Step 14 importer.

Deterministic: it replays the sanitised fixtures (a 3-call snapshot then a delta
batch with two Deletes) against a throwaway scratch schema, twice, to show the
event counts by type/object and that an unacknowledged replay creates no
duplicates. If FUSION_CLIENT_ID / FUSION_PASSWORD are set it also prints the real
``GetClientState`` (read-only — no cursor movement).

    TEST_DATABASE_URL=postgresql://localhost:5432/postgres \\
        uv run --project importers python -m iol_importers.fusion.demo
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import parse_qs
from xml.etree.ElementTree import fromstring

import httpx

from iol_importers.config import FusionCredentials, resolve_fusion_credentials
from iol_importers.listings._scratch import ScratchDB, scratch_schema

from .adapter import format_result, run
from .client import FusionClient

FEED = "demo-feed"
FIXTURE_CREDS = FusionCredentials(458, "demo-secret", "https://fusion.demo/v1/sync")
FIXTURES = Path(__file__).parent / "fixtures"
FULL_STORY = ("snapshot_1", "snapshot_2", "snapshot_3", "delta_1", "drained")
FLAGGED = Path(__file__).parent / "MAPPING_NOTES.md"


def _replay_transport(sequence: tuple[str, ...]) -> httpx.MockTransport:
    """A tiny state machine: advance on the current batch's token, replay on no token."""
    batches = [(FIXTURES / f"{n}.xml").read_text() for n in sequence]
    pos = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "RequestSnapshot":
            return httpx.Response(200, text="<RequestCompleted />")
        if method == "GetChanges":
            token = (parse_qs(request.content.decode()).get("commitToken") or [None])[0] or None
            current = batches[pos[0]]
            if token and token == fromstring(current).get("commitToken"):
                pos[0] = min(pos[0] + 1, len(batches) - 1)
                current = batches[pos[0]]
            return httpx.Response(200, text=current)
        return httpx.Response(404, text=f'<Exception type="UnknownMethod" method="{method}" />')

    return httpx.MockTransport(handler)


def _pass(db: ScratchDB, state_dir: Path, label: str) -> None:
    client = FusionClient(
        credentials=FIXTURE_CREDS,
        transport=_replay_transport(FULL_STORY),
        state_dir=state_dir,
        retry_base_delay=0.0,
    )
    try:
        result = run(
            feed_source_code=FEED,
            connect=db.data_connect,
            tracking_connect=db.tracking_connect,
            client=client,
            write_state=False,
        )
    finally:
        client.close()
    print(f"\n{label}:\n{format_result(result)}")


def main() -> int:
    creds = resolve_fusion_credentials()
    if creds is not None:
        with FusionClient() as client:
            state = client.get_client_state()
        print(
            f"live GetClientState: name={state.name} type={state.type} "
            f"totalSyncEvents={state.total_sync_events} "
            f"lastSequenceId={state.last_sync_event_sequence_id}"
        )
    else:
        print("FUSION_CLIENT_ID / FUSION_PASSWORD not set — fixture replay only")

    with scratch_schema() as db:
        state_dir = Path(tempfile.mkdtemp(prefix="fusion-demo-"))
        _pass(db, state_dir, "pass 1 (snapshot + delta)")
        _pass(db, state_dir, "pass 2 (same fixtures replayed)")

        with db.connect() as conn:
            listings = conn.execute("SELECT count(*) AS n FROM listings").fetchone()["n"]
            withdrawn = conn.execute(
                "SELECT count(*) AS n FROM listings WHERE status = 'Withdrawn'"
            ).fetchone()["n"]
            inactive = conn.execute(
                "SELECT count(*) AS n FROM agencies WHERE status = 'Inactive'"
            ).fetchone()["n"]
            errs = conn.execute("SELECT count(*) AS n FROM import_errors").fetchone()["n"]
    print(
        f"\nlistings: {listings}  withdrawn: {withdrawn}  agencies inactive: {inactive}  "
        f"import_errors: {errs}"
    )

    notes = FLAGGED.read_text()
    flagged = notes.split("## Deliberately not mapped", 1)[1].split("##", 1)[0].strip()
    print("\nfields left unmapped rather than guessed (see fusion/MAPPING_NOTES.md):\n")
    print(flagged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
