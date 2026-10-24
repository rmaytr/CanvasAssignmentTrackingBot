from datetime import time
from pathlib import Path

from canvas_tracker.bot.pairing import PairingCode
from canvas_tracker.hub.registry import OWNER_KEY
from canvas_tracker.hub.tenant import digest_grace_until, user_db_path
from canvas_tracker.render import copy
from tests.factories import NOW
from tests.hub_helpers import (
    BAD_TOKEN,
    GOOD_TOKEN,
    NO_PLANNER_TOKEN,
    build_hub,
    sign_up,
)


def texts(replies: list) -> list[str]:  # type: ignore[type-arg]
    return [r.text for r in replies]


async def test_invited_friend_signs_up_end_to_end(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    code = env.hub.registry.create_invite(NOW)
    replies = await env.signup.start(7, "Ana", code)
    assert texts(replies) == [copy.SIGNUP_INTRO, copy.ASK_URL]

    user = env.hub.registry.get_user(7)
    assert user is not None
    [reply] = await env.signup.text(user, "https://school.instructure.com/courses/5")
    assert reply.text == copy.ASK_TOKEN
    assert reply.keyboard[0][0].url == "https://school.instructure.com/profile/settings"

    user = env.hub.registry.get_user(7)
    assert user is not None
    replies = await env.signup.text(user, f"  {GOOD_TOKEN}\n")
    assert texts(replies) == [copy.TOKEN_SAVED, copy.ASK_TZ]
    # Canvas's own time zone is offered first
    assert replies[1].keyboard[0][0].callback_data == "su:tz:America/Chicago"

    for kind, value, expected in (
        ("tz", "America/Chicago", copy.ASK_DIGEST),
        ("dt", "07:30", copy.ASK_QUIET),
    ):
        user = env.hub.registry.get_user(7)
        assert user is not None
        [reply] = await env.signup.choice(user, kind, value)
        assert reply.text == expected

    user = env.hub.registry.get_user(7)
    assert user is not None
    [reply] = await env.signup.text(user, "11pm - 6am")
    assert reply.text.startswith("✅ All set!") and "7:30 AM" in reply.text

    user = env.hub.registry.get_user(7)
    assert user is not None and user.status == "active" and user.step is None
    tenant = env.hub.tenant(7)
    assert tenant is not None
    s = tenant.settings
    assert (s.tz, s.digest_time, s.quiet_start, s.quiet_end) == (
        "America/Chicago",
        time(7, 30),
        time(23, 0),
        time(6, 0),
    )
    assert s.canvas_host == "school.instructure.com"
    # the token is stored encrypted, nowhere in plain text
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("registry.db*"))
    assert GOOD_TOKEN.encode() not in raw
    assert env.hub.box.open(user.token_sealed or b"") == GOOD_TOKEN
    # only the time zone was kept from the profile
    assert b"Private Name" not in raw


async def test_strangers_need_an_invite_and_invites_work_once(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    assert texts(await env.signup.start(8, "X", None)) == [copy.INVITE_ONLY]
    assert texts(await env.signup.start(8, "X", "guessing")) == [copy.INVITE_ONLY]
    code = env.hub.registry.create_invite(NOW)
    await env.signup.start(9, "Y", code)
    assert texts(await env.signup.start(10, "Z", code)) == [copy.INVITE_ONLY]
    assert env.hub.registry.get_user(8) is None and env.hub.registry.get_user(10) is None


async def test_full_bot_keeps_the_invite_unused(tmp_path: Path) -> None:
    env = build_hub(tmp_path, max_users=1)
    await env.signup.start(1, "Owner", None)
    code = env.hub.registry.create_invite(NOW)
    assert texts(await env.signup.start(5, "F", code)) == [copy.BOT_FULL]
    env.hub.max_users = 2
    assert texts(await env.signup.start(5, "F", code))[0] == copy.SIGNUP_INTRO


async def test_owner_from_env_and_from_pairing_code(tmp_path: Path) -> None:
    env = build_hub(tmp_path / "a", owner=1)
    assert texts(await env.signup.start(1, "Me", None))[0] == copy.SIGNUP_INTRO
    user = env.hub.registry.get_user(1)
    assert user is not None and user.is_owner

    pairing = PairingCode(now=lambda: NOW, on_new_code=lambda _c: None)
    paired = build_hub(tmp_path / "b", owner=None, pairing=pairing)
    assert texts(await paired.signup.start(3, "Me", "WRONGCODE")) == [copy.INVITE_ONLY]
    replies = await paired.signup.start(3, "Me", pairing.code)
    assert texts(replies)[0] == copy.PAIRED_OWNER
    assert paired.hub.registry.get_state(OWNER_KEY) == "3" and paired.hub.owner_id() == 3


async def test_bad_addresses_are_refused(tmp_path: Path) -> None:
    env = build_hub(tmp_path, public=lambda host: host != "intranet.school.edu")
    await env.signup.start(1, "Me", None)
    for text, expected in (
        ("not a url", copy.URL_INVALID),
        ("http://school.instructure.com", copy.URL_INVALID),
        ("https://192.168.1.10", copy.URL_INVALID),
        ("intranet.school.edu", copy.URL_UNREACHABLE),
    ):
        user = env.hub.registry.get_user(1)
        assert user is not None
        assert texts(await env.signup.text(user, text)) == [expected]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "url" and user.canvas_base_url is None


async def test_token_problems_get_clear_answers(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.text(user, "school.instructure.com")
    for token, expected in (
        ("hello", copy.TOKEN_FORMAT),
        (BAD_TOKEN, copy.TOKEN_PROBLEMS["rejected"]),
        (NO_PLANNER_TOKEN, copy.TOKEN_PROBLEMS["no_planner"]),
    ):
        user = env.hub.registry.get_user(1)
        assert user is not None
        reply = expected.format(host="school.instructure.com")
        assert texts(await env.signup.text(user, token)) == [reply]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "token" and user.token_sealed is None


async def test_quiet_hours_may_not_hide_the_morning_list(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    for answer in ("school.instructure.com", GOOD_TOKEN, "Chicago", "7am"):
        user = env.hub.registry.get_user(1)
        assert user is not None
        await env.signup.text(user, answer)
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "quiet"
    assert texts(await env.signup.text(user, "00:00-08:00")) == [
        copy.QUIET_COVERS_DIGEST.format(digest="7:00 AM")
    ]
    assert texts(await env.signup.text(user, "nonsense")) == [copy.QUIET_INVALID]
    [reply] = await env.signup.text(user, "off")
    assert reply.text.startswith("✅ All set!") and "Quiet hours: off" in reply.text


async def test_settings_edits_rebuild_the_tenant(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    [reply] = env.signup.settings(user)
    assert "Morning list: 7:00 AM" in reply.text
    assert [b.callback_data for row in reply.keyboard for b in row] == [
        "set:tz",
        "set:dt",
        "set:qh",
        "set:tok",
    ]

    env.signup.begin_edit(user, "tz")
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "edit_tz"
    replies = await env.signup.text(user, "Pacific")
    assert texts(replies)[0] == copy.SAVED
    tenant = env.hub.tenant(1)
    assert tenant is not None and tenant.settings.tz == "America/Los_Angeles"

    # a morning time inside the quiet hours (23:00-06:00) is refused when editing
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "dt")
    user = env.hub.registry.get_user(1)
    assert user is not None
    [refused] = await env.signup.text(user, "5:30 am")
    assert refused.text.startswith("That's inside your quiet hours")

    user = env.hub.registry.get_user(1)
    assert user is not None
    assert texts(env.signup.cancel(user)) == [copy.CANCELLED]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step is None


async def test_replacing_the_token(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    user = env.hub.registry.get_user(1)
    assert user is not None
    env.signup.begin_edit(user, "tok")
    user = env.hub.registry.get_user(1)
    assert user is not None and user.step == "edit_token"
    assert texts(await env.signup.text(user, BAD_TOKEN)) == [
        copy.TOKEN_PROBLEMS["rejected"].format(host="school.instructure.com")
    ]
    new = "4242~NEWnewNEWnewNEWnewNEWnew0000"
    assert texts(await env.signup.text(user, new)) == [copy.TOKEN_SAVED]
    user = env.hub.registry.get_user(1)
    assert user is not None and env.hub.box.open(user.token_sealed or b"") == new


async def test_disconnect_erases_everything(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    await sign_up(env, 5)
    tenant = env.hub.tenant(5)
    assert tenant is not None
    await tenant.tick()
    assert user_db_path(tmp_path, 5).exists()
    user = env.hub.registry.get_user(5)
    assert user is not None
    assert texts(await env.signup.disconnect(user, confirmed=False)) == [copy.DISCONNECT_KEPT]
    assert texts(await env.signup.disconnect(user, confirmed=True)) == [copy.DISCONNECTED]
    assert env.hub.registry.get_user(5) is None and env.hub.tenant(5) is None
    assert not list(tmp_path.glob("users/5.db*"))
    assert env.hub.tenant(1) is not None  # nobody else is touched


async def test_owner_commands(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1, name="Owner")
    await sign_up(env, 5, name="Ben")
    owner = env.hub.registry.get_user(1)
    friend = env.hub.registry.get_user(5)
    assert owner is not None and friend is not None

    [link] = env.signup.invite(owner, "MyCanvasBot")
    assert "https://t.me/MyCanvasBot?start=" in link.text
    assert texts(env.signup.invite(friend, "MyCanvasBot")) == [copy.OWNER_ONLY]
    assert texts(env.signup.invite(owner, None)) == [copy.INVITE_NO_USERNAME]

    tenant = env.hub.tenant(5)
    assert tenant is not None
    await tenant.tick()
    [listing] = env.signup.users(owner)
    lines = listing.text.splitlines()
    assert lines[0] == "👥 Users (2 of 25)"
    assert lines[1].startswith("1. Owner (you) · school.instructure.com · ")
    assert lines[2].startswith("2. Ben · school.instructure.com · ✓ synced")
    assert texts(env.signup.users(friend)) == [copy.OWNER_ONLY]

    assert texts(await env.signup.remove(friend, "1")) == [copy.OWNER_ONLY]
    assert texts(await env.signup.remove(owner, "1")) == [copy.REMOVE_SELF]
    assert texts(await env.signup.remove(owner, "9")) == [copy.REMOVE_USAGE]
    assert texts(await env.signup.remove(owner, "2")) == [copy.REMOVED.format(name="Ben")]
    assert env.hub.registry.get_user(5) is None
    assert env.notifiers[5].sent[-1].text == copy.REMOVED_BY_OWNER


async def test_restart_during_signup_resumes_at_the_address(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await env.signup.start(1, "Me", None)
    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.text(user, "school.instructure.com")
    assert texts(await env.signup.start(1, "Me", None)) == [copy.ASK_URL]


def test_digest_grace_stays_on_the_same_day() -> None:
    assert digest_grace_until(time(8, 0)) == time(12, 0)
    assert digest_grace_until(time(21, 30)) == time(23, 59)
    assert digest_grace_until(time(19, 59)) == time(23, 59)
    assert digest_grace_until(time(19, 58)) == time(23, 58)
