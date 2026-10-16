"""Contract tests on real, scrubbed Canvas responses from the owner's M0 spike.

They skip until the owner commits the scrubbed files (see spike/README.md):
tests/fixtures/canvas/planner_items.json and assignment_groups_*.json.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.domain.models import ItemType
from canvas_tracker.sources.enrichment import map_assignment_groups
from canvas_tracker.sources.planner import map_planner_item

CANVAS = Path(__file__).parents[1] / "fixtures" / "canvas"
PLANNER = CANVAS / "planner_items.json"
GROUP_FILES = sorted(CANVAS.glob("assignment_groups_*.json"))
BASE = "https://canvas.example.edu"


@pytest.mark.skipif(not PLANNER.exists(), reason="waiting for the owner's scrubbed spike fixtures")
def test_real_planner_items_map() -> None:
    raw = json.loads(PLANNER.read_text(encoding="utf-8"))
    items = [map_planner_item(r, BASE) for r in raw]
    mapped = [i for i in items if i is not None]
    assert mapped, "no planner item mapped"
    assert all(i.due_at is not None and i.due_at.utcoffset() == timedelta(0) for i in mapped)
    assert any(i.type is ItemType.ASSIGNMENT for i in mapped)


@pytest.mark.skipif(not GROUP_FILES, reason="waiting for the owner's scrubbed spike fixtures")
def test_real_assignment_groups_map() -> None:
    totals = []
    for path in GROUP_FILES:
        _groups, _details, total = map_assignment_groups(
            1, json.loads(path.read_text(encoding="utf-8"))
        )
        totals.append(total)
    assert any(total > 0 for total in totals)
