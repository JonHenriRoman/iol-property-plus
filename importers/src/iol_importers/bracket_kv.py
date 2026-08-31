"""Parser for the bracketed key-value flat-file format shared by RT3, MyRoof and
PropertyPost — a legacy convention that appears in no standard format taxonomy.

    [[Listing_Start]]
    [[Area:Centurion/]]
    [[Description:First line of prose.

    Second paragraph./]]
    [[Image_URL:http://cdn.example/1.jpg/]]
    [[Image_URL:http://cdn.example/2.jpg/]]
    [[Listing_End]]

The three vendors share this grammar exactly; they differ only in which keys each
emits. This module is **purely syntactic** — it knows the delimiters and nothing
about any vendor's field meanings. Each record is yielded as an ordered list of
``(key, value)`` pairs with duplicates preserved, because a repeated key (e.g.
``Image_URL``) is how these feeds represent an array.

Grammar, as confirmed against real extracts from all three vendors:

* Records are delimited by the bare lines ``[[Listing_Start]]`` /
  ``[[Listing_End]]`` (no colon, no value). A record is emitted **only** on
  ``[[Listing_End]]`` — a run of unmatched ``[[Listing_Start]]`` lines (real:
  PropertyPost pads the end of its feed with hundreds of them) yields nothing.
* A pair is ``[[<Key>:<Value>/]]`` on one line, ``<Key>`` matching
  ``[A-Za-z0-9_]+``. The terminator is the ``]]`` at end of line; the ``/`` just
  before it is optional (real: ``[[onshowdate:2026-08-29]]``, and RT3's
  ``Address`` on some records). A value may contain ``/`` freely — URLs, GPS
  ``lat,lng`` pairs, ``R120/m²`` — because only the final ``]]`` at line end ends
  the pair, never a bare ``/`` or a ``]]`` earlier in the value.
* A value may span multiple physical lines (real: ``Description``), including
  blank lines, until a line whose end is ``]]``. Interior newlines are preserved;
  leading/trailing whitespace on the whole value is trimmed.
* An empty value is legitimate and is kept: ``[[Features_Description:/]]`` yields
  ``("Features_Description", "")``.

Known limitation (shared with the reference implementation): a value containing a
literal ``]]`` substring terminates the pair early. Not seen in any real extract.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass

_KEY = r"[A-Za-z0-9_]+"
# A complete single-line pair. The value is captured greedily up to the *last*
# `]]` on the line, so a `/` or a `]]` earlier in the value is safe; the
# terminator (` /]]`, `/]]`, `]]`) is trimmed off the capture afterwards.
_PAIR = re.compile(rf"^\s*\[\[({_KEY}):(.*)\]\]\s*$")
# Opens a value that does not close on its own line (a multi-line value).
_OPEN = re.compile(rf"^\s*\[\[({_KEY}):(.*)$")

_START = "[[Listing_Start]]"
_END = "[[Listing_End]]"


@dataclass(frozen=True, slots=True)
class BracketRecord:
    """One record: its ``(key, value)`` pairs in file order, duplicates kept."""

    pairs: tuple[tuple[str, str], ...]

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)

    def __bool__(self) -> bool:
        return bool(self.pairs)

    def keys(self) -> list[str]:
        """Every key in file order, including repeats."""
        return [k for k, _ in self.pairs]

    def get(self, key: str) -> str | None:
        """The first value for ``key`` (case-sensitive), or ``None``."""
        for k, v in self.pairs:
            if k == key:
                return v
        return None

    def get_all(self, key: str) -> list[str]:
        """Every value for ``key`` in file order — how a repeated key (an array,
        e.g. ``Image_URL``) is read back."""
        return [v for k, v in self.pairs if k == key]

    def as_dict(self) -> dict[str, list[str]]:
        """Every key mapped to its list of values, in file order. Generic — still
        no vendor field knowledge."""
        out: dict[str, list[str]] = {}
        for k, v in self.pairs:
            out.setdefault(k, []).append(v)
        return out


def iter_records(source: str | bytes) -> Iterator[BracketRecord]:
    """Yield one :class:`BracketRecord` per ``[[Listing_Start]]`` /
    ``[[Listing_End]]`` pair. Never raises on feed content."""
    text = source.decode("utf-8", "replace") if isinstance(source, bytes) else source
    text = text.lstrip("﻿")

    state = _State()
    for line in text.splitlines():
        record = state.feed(line)
        if record is not None:
            yield record
    # An unterminated value or an unclosed record at EOF is dropped.


def parse(source: str | bytes) -> list[BracketRecord]:
    """Eager :func:`iter_records`."""
    return list(iter_records(source))


def parse_file(path: str | os.PathLike[str], *, encoding: str = "utf-8") -> list[BracketRecord]:
    """Read ``path`` and parse it. Propagates ``OSError`` for a missing file."""
    with open(path, encoding=encoding, errors="replace") as handle:
        return list(iter_records(handle.read()))


@dataclass(slots=True)
class _State:
    """Line-by-line parser state: the open record and any open multi-line value."""

    current: list[tuple[str, str]] | None = None
    pending: _Pending | None = None

    def feed(self, line: str) -> BracketRecord | None:
        """Process one physical line; return a record when ``[[Listing_End]]``
        closes one, else ``None``."""
        if self.pending is not None and self._advance_pending(line):
            return None

        stripped = line.strip()
        if not stripped:
            return None
        if stripped == _START:
            self.current = []
            return None
        if stripped == _END:
            return self._close()
        if self.current is None:
            return None  # a pair line outside any record — ignored
        if pair := _PAIR.match(line):
            self.current.append((pair.group(1), _strip_terminator(pair.group(2))))
        elif opener := _OPEN.match(line):
            self.pending = _Pending(opener.group(1), [opener.group(2)])
        return None

    def _close(self) -> BracketRecord | None:
        if self.current is None:
            return None
        record = BracketRecord(tuple(self.current))
        self.current = None
        return record

    def _advance_pending(self, line: str) -> bool:
        """Offer ``line`` to the open multi-line value. Returns ``True`` when the
        line was consumed (interior or closing line), ``False`` when it belongs
        to the outer grammar (a marker or a fresh pair — the value's closer was
        omitted) and must still be processed by :meth:`feed`."""
        assert self.pending is not None
        if line.strip() in (_START, _END) or _PAIR.match(line):
            self.pending.flush(self.current)
            self.pending = None
            return False
        if line.rstrip().endswith("]]"):
            # Keep only the trailing '/' off the closer; outer whitespace is
            # handled when the buffered lines are joined and stripped.
            closer = line.rstrip()[:-2].rstrip()
            self.pending.buffer.append(closer[:-1] if closer.endswith("/") else closer)
            self.pending.flush(self.current)
            self.pending = None
            return True
        self.pending.buffer.append(line)
        return True


@dataclass(slots=True)
class _Pending:
    """A multi-line value still accumulating physical lines."""

    key: str
    buffer: list[str]

    def flush(self, current: list[tuple[str, str]] | None) -> None:
        if current is not None:
            current.append((self.key, "\n".join(self.buffer).strip()))


def _strip_terminator(value: str) -> str:
    """Drop a trailing delimiter ``/`` (and surrounding whitespace) from a value
    whose ``]]`` has already been removed."""
    value = value.rstrip()
    if value.endswith("/"):
        value = value[:-1]
    return value.strip()
