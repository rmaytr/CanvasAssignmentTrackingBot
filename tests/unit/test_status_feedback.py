"""Track 3: a fuller /status, /settings with every setting reachable, /feedback, /users."""

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from canvas_tracker.bot.commands import status_cmd
from canvas_tracker.domain.models import Item, ItemType
from canvas_tracker.hub.handlers import feedback_cmd, setup_button
from canvas_tracker.hub.hub import FEEDBACK_PER_WINDOW, FEEDBACK_WINDOW
from canvas_tracker.hub.signup import FEEDBACK_MAX_CHARS
from canvas_tracker.planning.keys import event_soon_key
from canvas_tracker.planning.news import latest_announcement_at, next_event_heads_up
from canvas_tracker.planning.timeutil import quiet_ends_at
from canvas_tracker.render import copy
from canvas_tracker.render.format import mask_email
from canvas_tracker.render.views import StatusInfo, email_label, render_status
from tests.factories import NOW, make_item, make_settings, make_snapshot
from tests.hub_helpers import GOOD_TOKEN, HubEnv, build_hub, sign_up
from tests.tg_helpers import callback_update, context, message_update, mock_bot

H = timedelta(hours=1)
NYZ = ZoneInfo("America/New_York")
S = make_settings(canvas_host="school.instructure.com")  # quiet 00:00-08:00 New York


def ny(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NYZ).astimezone(UTC)


def sent_texts(bot) -> list[str]:  # type: ignore[no-untyped-def]
    return [c.kwargs["text"] for c in bot.send_message.await_args_list]


def event(start: datetime, **kw: Any) -> Item:
    return make_item(type=ItemType.EVENT, plannable_type="calendar_event", due_at=start, **kw)


def announcement(posted: datetime, **kw: Any) -> Item:
    return make_item(type=ItemType.ANNOUNCEMENT, plannable_type="announcement", due_at=posted, **kw)


# --- pure helpers --------------------------------------------------------------------


def test_mask_email_keeps_the_first_letter_and_the_domain() -> None:
    assert mask_email("mia@school.edu") == "m***@school.edu"
    assert mask_email("m@school.edu") == "m***@school.edu"
    assert mask_email("not-an-address") == "***"
    assert email_label("mia@school.edu", available=True, masked=True) == "m***@school.edu"
    assert email_label("mia@school.edu", available=True, masked=False) == "mia@school.edu"
    assert email_label(None, available=True, masked=True) == copy.EMAIL_OFF_LABEL
    assert email_label("mia@school.edu", available=False, masked=True) == (
        copy.EMAIL_UNAVAILABLE_LABEL
    )


def test_quiet_ends_at_handles_windows_over_midnight() -> None:
    assert quiet_ends_at(ny(27, 23, 30), NYZ, time(23, 0), time(7, 0)) == ny(28, 7)
    assert quiet_ends_at(ny(28, 2), NYZ, time(23, 0), time(7, 0)) == ny(28, 7)
    assert quiet_ends_at(ny(28, 2), NYZ, time(0, 0), time(8, 0)) == ny(28, 8)


def test_next_event_heads_up_is_an_hour_before_the_soonest_event() -> None:
    now = ny(27, 12)
    later, sooner = event(ny(27, 18)), event(ny(27, 15))
    snap = make_snapshot([later, sooner])
    assert next_event_heads_up(now, snap, S) == ny(27, 14)
    # inside the lead time already: due now (the next tick sends it)
    assert next_event_heads_up(ny(27, 14, 30), snap, S) == ny(27, 14, 30)
    # once sent it no longer counts, so the next event's heads-up is shown
    sent = make_snapshot([later, sooner], sent_keys=frozenset({event_soon_key(sooner)}))
    assert next_event_heads_up(now, sent, S) == ny(27, 17)


def test_next_event_heads_up_skips_gone_past_and_hidden_events() -> None:
    now = ny(27, 12)
    gone = event(ny(27, 15), gone_at=now)
    past = event(ny(27, 11))
    early = event(ny(28, 7, 30))  # its whole lead hour is inside quiet hours (00-08)
    assert next_event_heads_up(now, make_snapshot([gone, past, early]), S) is None
    nine = event(ny(28, 8, 30))  # lead starts in quiet hours: the heads-up waits until 8:00
    assert next_event_heads_up(now, make_snapshot([nine]), S) == ny(28, 8)
    # /pause pushes it back, and drops it once the event would have started
    paused = make_snapshot([event(ny(27, 15))], pause_until=ny(27, 14, 30))
    assert next_event_heads_up(now, paused, S) == ny(27, 14, 30)
    hidden = make_snapshot([event(ny(27, 15))], pause_until=ny(27, 16))
    assert next_event_heads_up(now, hidden, S) is None


def test_latest_announcement_is_the_newest_posted_one() -> None:
    now = ny(27, 12)
    items = [
        announcement(ny(25, 9)),
        announcement(ny(27, 10)),
        announcement(ny(27, 11), gone_at=now),
        announcement(ny(27, 13)),  # not posted yet
        make_item(due_at=ny(27, 11, 30)),  # homework isn't an announcement
    ]
    assert latest_announcement_at(now, make_snapshot(items)) == ny(27, 10)
    assert latest_announcement_at(now, make_snapshot([])) is None


def base_info(**kw: object) -> StatusInfo:
    values: dict[str, object] = {
        "last_successful_sync_at": NOW,
        "auth_failed_since": None,
        "next_digest_at": NOW + 20 * H,
        "next_slot_at": None,
        "pause_until": None,
        "version": "x",
    }
    values.update(kw)
    return StatusInfo(**values)  # type: ignore[arg-type]


def test_status_shows_email_rhythm_event_and_announcement_lines() -> None:
    text = render_status(base_info(), NOW, S).text
    assert f"Email: {copy.EMAIL_UNAVAILABLE_LABEL}" in text
    assert "Reminders: every 2 hours, for work due within 24 hours" in text
    assert "Next event" not in text and "Last announcement" not in text

    off = render_status(base_info(email_available=True), NOW, S).text
    assert f"Email: {copy.EMAIL_OFF_LABEL}" in off
    full = render_status(
        base_info(
            email_available=True,
            email_address="mia@school.edu",
            next_event_at=NOW + 2 * H,
            last_announcement_at=NOW - 26 * H,
            pause_until=NOW + H,
        ),
        NOW,
        S,
    ).text
    assert "Email: m***@school.edu" in full and "mia@" not in full
    assert "Next event heads-up: today 2:00 PM" in full
    assert "Last announcement: yesterday 10:00 AM" in full
    # pausing shows the pause and keeps the rhythm line
    assert "Paused until today 1:00 PM" in full and "Reminders: every 2 hours" in full
    lines = full.splitlines()
    assert lines[-1] == "Version: x" and len(lines) == 10


# --- /status through the hub -----------------------------------------------------------


async def with_email(env: HubEnv, telegram_id: int, address: str) -> None:
    env.hub.registry.update_user(telegram_id, email_sealed=env.hub.box.seal(address))
    tenant = await env.hub.refresh(telegram_id)
    if tenant is not None and tenant.running is not None:
        await tenant.running  # its first sync, so it can't race the test's own items


async def test_status_command_shows_the_users_own_masked_email(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    await sign_up(env, 5)
    await with_email(env, 1, "owner@school.edu")
    await with_email(env, 5, "ben@college.edu")
    tenant = env.hub.tenant(5)
    assert tenant is not None
    tenant.store.upsert_items(
        [event(NOW + 3 * H, title="Review session"), announcement(NOW - H)], NOW
    )
    bot = mock_bot()
    await status_cmd(tenant.deps)(message_update("/status", user_id=5, bot=bot), context())
    [text] = sent_texts(bot)
    assert "Email: b***@college.edu" in text
    assert "owner" not in text and "o***" not in text  # nobody else's address
    assert "Next event heads-up: " in text and "Last announcement: " in text
    assert "Review session" not in text  # compact: times only

    bare = build_hub(tmp_path / "no-mail")
    await sign_up(bare, 1)
    plain = bare.hub.tenant(1)
    assert plain is not None
    bot = mock_bot()
    await status_cmd(plain.deps)(message_update("/status", user_id=1, bot=bot), context())
    assert f"Email: {copy.EMAIL_UNAVAILABLE_LABEL}" in sent_texts(bot)[0]


# --- /settings ---------------------------------------------------------------------------


async def test_settings_shows_email_and_its_button_explains_email(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [reply] = env.signup.settings(user)
    assert f"Email: {copy.EMAIL_OFF_LABEL}" in reply.text
    assert "Reminders: every 2 hours, for work due within 24 hours" in reply.text
    assert "set:em" in [b.callback_data for row in reply.keyboard for b in row]
    assert [r.text for r in env.signup.begin_edit(user, "em")] == [copy.EMAIL_STATUS_OFF]

    await with_email(env, 1, "me@school.edu")
    user = env.hub.registry.get_user(1)
    assert user is not None
    [reply] = env.signup.settings(user)
    assert "Email: me@school.edu" in reply.text  # the user's own chat: the full address
    [info] = env.signup.begin_edit(user, "em")
    assert info.text == copy.EMAIL_STATUS_ON.format(address="me@school.edu")

    # the button also leaves a half-finished settings change
    env.signup.begin_edit(user, "tz")
    bot = mock_bot()
    await setup_button(env.signup)(callback_update("set:em", user_id=1, bot=bot), context())
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step is None
    assert sent_texts(bot) == [copy.EMAIL_STATUS_ON.format(address="me@school.edu")]


async def test_settings_says_when_email_is_not_available(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [reply] = env.signup.settings(user)
    assert f"Email: {copy.EMAIL_UNAVAILABLE_LABEL}" in reply.text
    assert [r.text for r in env.signup.begin_edit(user, "em")] == [copy.EMAIL_UNAVAILABLE]


async def test_email_button_does_nothing_during_sign_up(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    assert [r.text for r in env.signup.begin_edit(user, "em")] == [copy.ASK_URL]


# --- /feedback ----------------------------------------------------------------------------


async def feedback(env: HubEnv, telegram_id: int, text: str, username: str | None = None) -> str:
    user = env.hub.registry.get_user(telegram_id)
    assert user is not None
    [reply] = await env.signup.feedback(user, text, username)
    return reply.text


def owner_inbox(env: HubEnv) -> list[str]:
    return [m.text for m in env.notifiers[1].sent]


async def test_feedback_reaches_the_owner_without_canvas_data(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 5, name="Ben <b>", url="secret-school.instructure.com")
    env.notifiers[1].sent.clear()
    assert await feedback(env, 5, "The list came <late> & twice", "ben_k") == copy.FEEDBACK_SENT
    [note] = owner_inbox(env)
    assert note == copy.FEEDBACK_TO_OWNER.format(
        name="Ben &lt;b&gt;",
        telegram_id=5,
        username=", @ben_k",
        signup="",
        text="The list came &lt;late&gt; &amp; twice",
    )
    assert "secret-school" not in note and GOOD_TOKEN not in note


async def test_feedback_from_someone_still_signing_up_says_so(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await env.signup.start(5, "New", env.hub.registry.create_invite(NOW))
    env.notifiers[1].sent.clear()
    assert await feedback(env, 5, "I'm stuck on the token step") == copy.FEEDBACK_SENT
    [note] = owner_inbox(env)
    assert copy.FEEDBACK_SIGNING_UP in note and "@" not in note


async def test_feedback_is_rate_limited_and_failures_dont_count(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    env.notifiers[1].sent.clear()
    env.notifiers[1].fail_times = 1
    assert await feedback(env, 5, "lost") == copy.FEEDBACK_FAILED
    for n in range(FEEDBACK_PER_WINDOW):
        assert await feedback(env, 5, f"note {n}") == copy.FEEDBACK_SENT
    assert await feedback(env, 5, "one too many") == copy.FEEDBACK_TOO_MANY.format(minutes=60)
    assert len(owner_inbox(env)) == FEEDBACK_PER_WINDOW
    env.clock.now = NOW + FEEDBACK_WINDOW
    assert await feedback(env, 5, "an hour later") == copy.FEEDBACK_SENT


async def test_feedback_refuses_empty_long_and_token_notes(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    env.notifiers[1].sent.clear()
    assert await feedback(env, 5, "   ") == copy.FEEDBACK_USAGE
    too_long = "x" * (FEEDBACK_MAX_CHARS + 1)
    assert await feedback(env, 5, too_long) == copy.FEEDBACK_TOO_LONG.format(
        limit=FEEDBACK_MAX_CHARS
    )
    assert await feedback(env, 5, f"my token is {GOOD_TOKEN}") == copy.FEEDBACK_HAS_TOKEN
    assert owner_inbox(env) == []
    # refused notes don't use up the hourly allowance
    for _ in range(FEEDBACK_PER_WINDOW):
        assert await feedback(env, 5, "ok") == copy.FEEDBACK_SENT


async def test_the_owners_own_feedback_is_just_acknowledged(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    env.notifiers[1].sent.clear()
    assert await feedback(env, 1, "note to self") == copy.FEEDBACK_OWNER
    assert owner_inbox(env) == []


async def test_feedback_handler_keeps_line_breaks_and_deletes_tokens(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    env.notifiers[1].sent.clear()
    bot = mock_bot()
    update = message_update("/feedback first line\nsecond line", user_id=5, bot=bot)
    await feedback_cmd(env.signup)(update, context())
    assert sent_texts(bot) == [copy.FEEDBACK_SENT]
    [note] = owner_inbox(env)
    assert note.endswith("first line\nsecond line")

    bot = mock_bot()
    await feedback_cmd(env.signup)(message_update("/feedback", user_id=5, bot=bot), context())
    assert sent_texts(bot) == [copy.FEEDBACK_USAGE]

    bot = mock_bot()
    leaked = message_update(f"/feedback here {GOOD_TOKEN}", user_id=5, bot=bot)
    await feedback_cmd(env.signup)(leaked, context())
    bot.delete_message.assert_awaited()
    assert sent_texts(bot) == [copy.TOKEN_DELETED, copy.FEEDBACK_HAS_TOKEN]
    assert len(owner_inbox(env)) == 1


def test_feedback_is_listed_in_help_and_the_command_menu() -> None:
    assert "/feedback" in copy.HELP
    assert "feedback" in dict(copy.BOT_COMMANDS)


# --- owner /users ---------------------------------------------------------------------------


async def test_users_shows_whether_each_user_has_email(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 5, name="Ben")
    await with_email(env, 5, "ben@college.edu")
    owner = env.hub.registry.get_user(1)
    assert owner is not None
    [listing] = env.signup.users(owner)
    lines = listing.text.splitlines()
    assert lines[1].endswith(" · email no")
    assert lines[2].endswith(" · email yes")
    assert "ben@" not in listing.text and "b***" not in listing.text

    # on a bot without email nobody gets any, whatever is stored
    env.hub.mailer_factory = None
    [listing] = env.signup.users(owner)
    assert listing.text.count("email no") == 2
