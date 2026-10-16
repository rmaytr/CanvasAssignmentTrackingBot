from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from canvas_tracker.domain.done_rule import DoneSource, done_source, is_done
from tests.factories import NOW, make_item

CASES = [
    ("redo beats submitted", {"submitted": True, "redo_request": True}, None),
    ("marked complete", {"marked_complete": True}, DoneSource.CANVAS_MARKED),
    ("submitted", {"submitted": True}, DoneSource.SUBMITTED),
    ("submitted but un-marked", {"submitted": True, "marked_complete": False}, None),
    ("excused", {"excused": True, "missing": True}, DoneSource.EXCUSED),
    (
        "graded offline",
        {"graded": True, "submission_types": ("on_paper",)},
        DoneSource.GRADED_OFFLINE,
    ),
    (
        "graded zero online stays open",
        {"graded": True, "submission_types": ("online_upload",)},
        None,
    ),
    (
        "mixed types not offline",
        {"graded": True, "submission_types": ("on_paper", "online_upload")},
        None,
    ),
    ("graded no types", {"graded": True, "submission_types": ()}, None),
    ("nothing set", {}, None),
]


@pytest.mark.parametrize(("name", "fields", "expected"), CASES, ids=[c[0] for c in CASES])
def test_done_source(name: str, fields: dict[str, Any], expected: DoneSource | None) -> None:
    item = make_item(**fields)
    assert done_source(item) == expected
    assert is_done(item) is (expected is not None)


def test_bot_done_holds_until_due_changes() -> None:
    item = make_item()
    assert item.due_at is not None
    done = replace(item, bot_done_at=NOW, bot_done_due_at=item.due_at)
    assert done_source(done) is DoneSource.BOT
    extended = replace(done, due_at=item.due_at + timedelta(days=2))
    assert done_source(extended) is None


def test_redo_request_overrides_bot_done() -> None:
    item = make_item(redo_request=True)
    done = replace(item, bot_done_at=NOW, bot_done_due_at=item.due_at)
    assert done_source(done) is None
