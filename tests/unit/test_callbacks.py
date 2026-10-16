from datetime import datetime, timedelta

import pytest

from canvas_tracker.bot.callbacks import on_callback, parse_callback, snooze_until
from canvas_tracker.bot.deps import BotDeps
from canvas_tracker.render import copy
from tests.factories import NOW, make_item
from tests.tg_helpers import callback_update, context, make_deps, mock_bot


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def deps_with_item(due_in: timedelta = timedelta(hours=3)) -> tuple[BotDeps, Clock, int]:
    clock = Clock()
    deps = make_deps(owner=77, now=clock)
    deps.store.upsert_items([make_item(plannable_id=1, due_in=due_in)], NOW)
    [item] = deps.store.snapshot().items
    assert item.db_id is not None
    return deps, clock, item.db_id


async def press(deps: BotDeps, data: str):  # type: ignore[no-untyped-def]
    bot = mock_bot()
    await on_callback(deps)(callback_update(data, bot=bot), context())
    assert bot.answer_callback_query.await_count == 1
    return bot, bot.answer_callback_query.await_args.kwargs.get("text")


def test_parse_callback() -> None:
    assert parse_callback("d:12") == ("d", 12)
    assert parse_callback("u:3") == ("u", 3)
    for bad in ("z:1", "d:x", "d:1:2", "", "d:"):
        assert parse_callback(bad) is None


def test_snooze_until_caps_before_deadline() -> None:
    assert snooze_until(NOW, NOW + timedelta(hours=3)) == NOW + timedelta(hours=2)
    due = NOW + timedelta(hours=1, minutes=50)
    assert snooze_until(NOW, due) == due - timedelta(minutes=30)
    assert snooze_until(NOW, NOW + timedelta(minutes=30)) is None


async def test_done_marks_item_and_swaps_buttons_for_undo() -> None:
    deps, _clock, db_id = deps_with_item()
    bot, text = await press(deps, f"d:{db_id}")
    assert text == copy.DONE
    item = deps.store.get_item(db_id)
    assert item is not None and item.bot_done_at == NOW
    markup = bot.edit_message_reply_markup.await_args.kwargs["reply_markup"]
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    assert rows == [[("✔️ 1 done · ↩️ Undo", f"u:{db_id}")], [("✅ Done 2", "d:2")]]


async def test_undo_within_window_then_expired() -> None:
    deps, clock, db_id = deps_with_item()
    await press(deps, f"d:{db_id}")
    clock.now = NOW + timedelta(minutes=5)
    _bot, text = await press(deps, f"u:{db_id}")
    item = deps.store.get_item(db_id)
    assert text == copy.UNDONE and item is not None and item.bot_done_at is None
    clock.now = NOW
    await press(deps, f"d:{db_id}")
    clock.now = NOW + timedelta(minutes=11)
    _bot, text = await press(deps, f"u:{db_id}")
    item = deps.store.get_item(db_id)
    assert text == copy.UNDO_EXPIRED and item is not None and item.bot_done_at is not None


async def test_snooze_sets_until_and_refuses_when_too_late() -> None:
    deps, _clock, db_id = deps_with_item()
    _bot, text = await press(deps, f"s:{db_id}")
    item = deps.store.get_item(db_id)
    assert item is not None and item.snoozed_until == NOW + timedelta(hours=2)
    assert text == copy.SNOOZED.format(until="2:00 PM")
    late, _c, late_id = deps_with_item(due_in=timedelta(minutes=20))
    _bot, text = await press(late, f"s:{late_id}")
    item = late.store.get_item(late_id)
    assert text == copy.SNOOZE_TOO_LATE and item is not None and item.snoozed_until is None


async def test_stop_and_undo_stop() -> None:
    deps, _clock, db_id = deps_with_item(due_in=timedelta(hours=-1))
    _bot, text = await press(deps, f"x:{db_id}")
    item = deps.store.get_item(db_id)
    assert text == copy.STOPPED and item is not None and item.stop_reminders
    _bot, text = await press(deps, f"u:{db_id}")
    item = deps.store.get_item(db_id)
    assert text == copy.UNDONE and item is not None and not item.stop_reminders


@pytest.mark.parametrize("data", ["d:999", "nonsense", "z:1"])
async def test_stale_or_bad_buttons_answer_gone(data: str) -> None:
    deps, _clock, _db_id = deps_with_item()
    _bot, text = await press(deps, data)
    assert text == copy.ITEM_GONE


async def test_gone_item_answers_gone() -> None:
    deps, _clock, db_id = deps_with_item()
    deps.store.mark_gone((NOW - timedelta(days=1), NOW + timedelta(days=1)), set(), NOW)
    _bot, text = await press(deps, f"d:{db_id}")
    assert text == copy.ITEM_GONE
