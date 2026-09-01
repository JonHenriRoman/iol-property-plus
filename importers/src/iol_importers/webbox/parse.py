"""Stream-parse a Webbox ``feed.xml`` into :class:`Property` records.

Stdlib ``xml.etree.ElementTree.iterparse`` — no lxml/defusedxml (the same
"trusted vendor over TLS, stdlib ET resolves no external entities" call
:mod:`iol_importers.allsa` and :mod:`iol_importers.fusion` make). ``iterparse``
streams the document rather than loading it whole, and keying on the element tag
name makes the parser indifferent to the outer structure.

Webbox's real shape (confirmed against production captures of 21 and 411
properties) nests the repeated ``<property>`` two levels inside ``<agency>``,
beside that agency's own ``<agency-details>``:

    <agencies>
      <agency>
        <agency-details>…</agency-details>
        <properties>
          <property>…</property>
          <property>…</property>
        </properties>
      </agency>
    </agencies>

This parser also accepts a bare ``<property>`` document root and a consecutive
stream of ``<property>`` elements — :attr:`ParseResult.outer_form` reports which
was actually seen. CDATA (``heading`` / ``description`` / ``address``) is returned
transparently; an empty ``<amount/>`` / ``<virtual-tour/>`` yields ``""``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from xml.etree.ElementTree import Element, ParseError, iterparse

# Direct <property> children that group leaf elements rather than being leaves.
_NESTED_TAGS = frozenset({"price", "coordinates", "location", "land-size", "property-size"})


class WebboxParseError(RuntimeError):
    """The body is not a well-formed Webbox XML document."""


@dataclass(frozen=True, slots=True)
class Property:
    fields: dict[str, str]  # scalar leaf children of <property>
    nested: dict[str, dict[str, str]]  # price / coordinates / location / land-size / property-size
    features: tuple[tuple[str, str], ...]  # ordered (tag, value); duplicate tags dropped first-wins
    agents: tuple[dict[str, str], ...]  # each <agent>'s leaf children, in feed order
    images: tuple[str, ...]
    videos: tuple[str, ...]
    agency: dict[str, str]  # flattened <agency-details> for this property's <agency>; {} if none
    duplicate_feature_elements: int = 0


@dataclass
class ParseResult:
    properties: list[Property] = field(default_factory=list)
    outer_form: str = "streamed"  # "wrapped" | "bare-property" | "streamed"
    agencies_seen: int = 0
    duplicate_feature_elements: int = 0


def _leaf_text(el: Element) -> str:
    return (el.text or "").strip()


def _flatten(el: Element) -> dict[str, str]:
    """One level of leaf children -> ``{tag: text}``. A nested child (e.g.
    ``head-office-location``) is recorded as its own flattened sub-block joined
    with '/', enough for raw_data; structured access uses the dedicated fields."""
    out: dict[str, str] = {}
    for child in el:
        if len(child) == 0:
            out[child.tag] = _leaf_text(child)
        else:
            for sub in child:
                out[f"{child.tag}/{sub.tag}"] = _leaf_text(sub)
    return out


def _parse_features(node: Element) -> tuple[tuple[tuple[str, str], ...], int]:
    seen: dict[str, str] = {}
    dropped = 0
    for child in node:
        if child.tag in seen:
            dropped += 1
            continue
        seen[child.tag] = _leaf_text(child)
    return tuple(seen.items()), dropped


def _build_property(node: Element, agency: dict[str, str]) -> Property:
    fields: dict[str, str] = {}
    nested: dict[str, dict[str, str]] = {}
    features: tuple[tuple[str, str], ...] = ()
    dropped = 0
    agents: list[dict[str, str]] = []
    images: list[str] = []
    videos: list[str] = []

    for child in node:
        tag = child.tag
        if tag == "features":
            features, dropped = _parse_features(child)
        elif tag == "agents":
            agents = [_flatten(a) for a in child if a.tag == "agent"]
        elif tag == "images":
            images = [_leaf_text(img) for img in child if _leaf_text(img)]
        elif tag == "videos":
            videos = [_leaf_text(v) for v in child if _leaf_text(v)]
        elif tag in _NESTED_TAGS:
            nested[tag] = _flatten(child)
        else:
            fields[tag] = _leaf_text(child)

    return Property(
        fields=fields,
        nested=nested,
        features=features,
        agents=tuple(agents),
        images=tuple(images),
        videos=tuple(videos),
        agency=dict(agency),
        duplicate_feature_elements=dropped,
    )


def parse_feed(body: bytes | str) -> ParseResult:
    """``bytes`` / ``str`` -> :class:`ParseResult`. Raises :class:`WebboxParseError`
    on a malformed body. An empty document yields an empty result (the adapter
    refuses to reconcile on an empty pull)."""
    source = BytesIO(body.encode("utf-8") if isinstance(body, str) else body)
    result = ParseResult()
    agency: dict[str, str] = {}
    last_tag = ""

    try:
        for _event, elem in iterparse(source, events=("end",)):
            last_tag = elem.tag
            if elem.tag == "agency-details":
                agency = _flatten(elem)
                elem.clear()
            elif elem.tag == "property":
                prop = _build_property(elem, agency)
                result.properties.append(prop)
                result.duplicate_feature_elements += prop.duplicate_feature_elements
                elem.clear()
            elif elem.tag == "agency":
                result.agencies_seen += 1
                agency = {}
    except ParseError as exc:
        raise WebboxParseError(f"not well-formed XML: {exc}") from exc

    if result.agencies_seen:
        result.outer_form = "wrapped"
    elif last_tag == "property":
        result.outer_form = "bare-property"
    else:
        result.outer_form = "streamed"
    return result
