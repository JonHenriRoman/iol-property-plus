"""Offline unit tests — the AreaTree crosswalk."""

from __future__ import annotations

from xml.etree.ElementTree import fromstring

from fusion_mock import load
from iol_importers.fusion.areatree import AreaTree


def _tree_element(name: str):
    changes = fromstring(load(name))
    return changes.find(".//AreaTree")


def test_apply_element_flattens_hierarchy():
    tree = AreaTree()
    seen = tree.apply_element(_tree_element("snapshot_3"))
    assert seen == 4
    assert tree.suburb_name("8") == "Claremont"
    assert tree.entry("10") == {
        "suburb": "Sandton",
        "city": "Johannesburg",
        "province": "Gauteng",
        "country": "South Africa",
    }
    assert tree.suburb_name("999") is None


def test_remove_suburb_ref():
    tree = AreaTree()
    tree.apply_element(_tree_element("snapshot_3"))
    assert tree.remove("SuburbRef", "9") is True
    assert "9" not in tree
    assert tree.remove("SuburbRef", "9") is False


def test_round_trips_through_disk(tmp_path):
    tree = AreaTree()
    tree.apply_element(_tree_element("snapshot_3"))
    path = tmp_path / "fusion" / "area_tree.json"
    tree.save(path)
    reloaded = AreaTree.load(path)
    assert reloaded.suburb_name("11") == "Rosebank"
    assert len(reloaded) == 4


def test_load_missing_file_is_empty(tmp_path):
    assert len(AreaTree.load(tmp_path / "nope.json")) == 0
