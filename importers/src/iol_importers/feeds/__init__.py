"""Shared scaffolding for vendor feed importers — import-run and error tracking.

No vendor-specific parsing lives here. Every feed importer opens an ``import_run``,
reports per-record outcomes, and lets the context manager close the ``import_jobs``
row with accurate counts — as ``Success``, ``PartialSuccess`` or ``Failed``.
"""

from .run import (
    ErrorType,
    FeedSourceNotFoundError,
    ImportRun,
    RunCounts,
    SchemaNotReadyError,
    import_run,
)

__all__ = [
    "ErrorType",
    "FeedSourceNotFoundError",
    "ImportRun",
    "RunCounts",
    "SchemaNotReadyError",
    "import_run",
]
