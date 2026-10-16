from datetime import timedelta
from unittest.mock import AsyncMock

from canvas_tracker.bot.commands import digest_cmd, pause_cmd, status_cmd, sync_cmd
from canvas_tracker.render import copy
from canvas_tracker.runtime.sync import SyncOutcome
from canvas_tracker.store.repo import PAUSE_UNTIL
from tests.factories import NOW, make_item
from tests.tg_helpers import context, make_deps, message_update, mock_bot


async def test_pause_sets_and_clears_state() -> None:
    deps = make_deps(owner=77)
    bot = mock_bot()
    await pause_cmd(deps)(message_update("/pause 3h", bot=bot), context("3h"))
    assert deps.store.get_time(PAUSE_UNTIL) == NOW + timedelta(hours=3)
    await pause_cmd(deps)(message_update("/pause off", bot=bot), context("off"))
    assert deps.store.get_time(PAUSE_UNTIL) is None
    assert bot.send_message.await_args.kwargs["text"] == copy.PAUSE_OFF


async def test_pause_without_argument_shows_usage() -> None:
    deps = make_deps(owner=77)
    bot = mock_bot()
    await pause_cmd(deps)(message_update("/pause", bot=bot), context())
    assert bot.send_message.await_args.kwargs["text"] == copy.PAUSE_USAGE


async def test_digest_command_does_not_claim_the_daily_key() -> None:
    deps = make_deps(owner=77)
    bot = mock_bot()
    await digest_cmd(deps)(message_update("/digest", bot=bot), context())
    assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    assert deps.store.snapshot().sent_keys == frozenset()


async def test_sync_reports_count_of_open_items() -> None:
    deps = make_deps(owner=77)
    deps.store.upsert_items(
        [make_item(plannable_id=1), make_item(plannable_id=2, submitted=True)], NOW
    )
    deps.sync = AsyncMock()
    deps.sync.sync.return_value = SyncOutcome.OK
    bot = mock_bot()
    await sync_cmd(deps)(message_update("/sync", bot=bot), context())
    assert bot.send_message.await_args.kwargs["text"] == copy.SYNC_OK.format(count=1)
    deps.sync.sync.return_value = SyncOutcome.AUTH_FAILED
    await sync_cmd(deps)(message_update("/sync", bot=bot), context())
    assert bot.send_message.await_args.kwargs["text"] == copy.SYNC_FAILED[SyncOutcome.AUTH_FAILED]


async def test_status_command_mentions_version() -> None:
    deps = make_deps(owner=77)
    bot = mock_bot()
    await status_cmd(deps)(message_update("/status", bot=bot), context())
    assert "0.1.0" in bot.send_message.await_args.kwargs["text"]
