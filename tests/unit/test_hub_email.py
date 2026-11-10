import re
from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.hub.email import (
    CODE_LIFETIME,
    MAX_ATTEMPTS,
    RESEND_AFTER,
    looks_like_school_address,
)
from canvas_tracker.hub.handlers import email_cmd
from canvas_tracker.render import copy
from tests.factories import NOW
from tests.hub_helpers import GOOD_TOKEN, OTHER_TOKEN, HubEnv, build_hub, sign_up
from tests.integration.sim_env import ScenarioItem
from tests.tg_helpers import context, message_update, mock_bot


def planner(item_id: int, title: str, due_in: timedelta) -> list[dict]:  # type: ignore[type-arg]
    data = ScenarioItem(item_id, title, lambda _t: NOW + due_in).planner_json(NOW)
    assert data is not None
    return [data]


async def email(env: HubEnv, telegram_id: int, arg: str | None = None) -> list[str]:
    user = env.hub.registry.get_user(telegram_id)
    assert user is not None
    return [r.text for r in await env.signup.email_command(user, arg)]


def last_code(env: HubEnv) -> str:
    _to, msg = env.outbox.sent[-1]
    match = re.search(r"\b(\d{6})\b", msg.subject)
    assert match is not None
    return match.group(1)


async def confirmed(env: HubEnv, telegram_id: int, address: str) -> None:
    await email(env, telegram_id, address)
    assert await email(env, telegram_id, last_code(env)) == [
        copy.EMAIL_VERIFIED.format(address=address)
    ]


async def test_email_unavailable_without_a_mail_server(tmp_path: Path) -> None:
    env = build_hub(tmp_path)
    await sign_up(env, 1)
    assert await email(env, 1, "me@school.edu") == [copy.EMAIL_UNAVAILABLE]


async def test_add_confirm_and_turn_off(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    assert await email(env, 1) == [copy.EMAIL_STATUS_OFF]

    replies = await email(env, 1, "Me@School.EDU")
    assert replies == [copy.EMAIL_CODE_SENT.format(address="Me@school.edu"), copy.EMAIL_SCHOOL_HINT]
    to, msg = env.outbox.sent[0]
    assert to == "Me@school.edu"
    code = last_code(env)
    assert code in msg.text

    user = env.hub.registry.get_user(1)
    assert user is not None and user.email_sealed is None  # nothing until confirmed
    assert user.email_pending_sealed is not None and b"school" not in user.email_pending_sealed
    assert user.email_code_hash is not None and code not in user.email_code_hash

    assert await email(env, 1, code) == [copy.EMAIL_VERIFIED.format(address="Me@school.edu")]
    tenant = env.hub.tenant(1)
    assert tenant is not None and tenant.settings.email
    assert await email(env, 1) == [copy.EMAIL_STATUS_ON.format(address="Me@school.edu")]
    settings = env.signup.settings(env.hub.registry.get_user(1))  # type: ignore[arg-type]
    assert "Email: Me@school.edu" in settings[0].text

    assert await email(env, 1, "off") == [copy.EMAIL_TURNED_OFF]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.email_sealed is None
    tenant = env.hub.tenant(1)
    assert tenant is not None and not tenant.settings.email
    assert await email(env, 1, "off") == [copy.EMAIL_ALREADY_OFF]


async def test_invalid_addresses_are_refused(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    for bad in ("nope", "a@b", "a@b.com,c@d.com", "x@y.com\r\nBcc: z@q.com", "<a@b.com>"):
        assert await email(env, 1, bad) == [copy.EMAIL_INVALID], bad
    assert env.outbox.sent == []


async def test_wrong_codes_lock_after_five_tries(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    await email(env, 1, "me@school.edu")
    wrong = "000000" if last_code(env) != "000000" else "111111"
    for _ in range(MAX_ATTEMPTS - 1):
        assert await email(env, 1, wrong) == [copy.EMAIL_CODE_WRONG]
    assert await email(env, 1, wrong) == [copy.EMAIL_CODE_LOCKED]
    assert await email(env, 1, last_code(env)) == [copy.EMAIL_NO_PENDING]


async def test_code_expires(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    await email(env, 1, "me@school.edu")
    env.clock.now = NOW + CODE_LIFETIME
    assert await email(env, 1, last_code(env)) == [copy.EMAIL_CODE_EXPIRED]


async def test_codes_cant_be_requested_back_to_back(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    await email(env, 1, "me@school.edu")
    assert await email(env, 1, "other@school.edu") == [copy.EMAIL_WAIT]
    assert len(env.outbox.sent) == 1
    env.clock.now = NOW + RESEND_AFTER
    await email(env, 1, "other@school.edu")
    assert len(env.outbox.sent) == 2


async def test_failed_code_email_keeps_nothing(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    env.outbox.fail = True
    assert await email(env, 1, "me@school.edu") == [copy.EMAIL_SEND_FAILED]
    user = env.hub.registry.get_user(1)
    assert user is not None and user.email_pending_sealed is None


async def test_one_users_code_doesnt_confirm_anothers_address(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1, token=GOOD_TOKEN)
    await sign_up(env, 5, token=OTHER_TOKEN)
    await email(env, 1, "ana@school.edu")
    ana_code = last_code(env)
    env.clock.now = NOW + RESEND_AFTER
    await email(env, 5, "ben@school.edu")
    if ana_code != last_code(env):
        assert await email(env, 5, ana_code) == [copy.EMAIL_CODE_WRONG]


async def test_deadline_email_goes_to_the_confirmed_address(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    env.canvas.items = {
        GOOD_TOKEN: planner(11, "Essay", timedelta(hours=1, minutes=30)),
        OTHER_TOKEN: planner(22, "Ben lab", timedelta(hours=1, minutes=30)),
    }
    await sign_up(env, 1, token=GOOD_TOKEN)
    await sign_up(env, 5, token=OTHER_TOKEN)  # Ben never turns email on
    await confirmed(env, 1, "ana@school.edu")
    env.outbox.sent.clear()

    await env.hub.tick_all()
    [(to, msg)] = env.outbox.sent
    assert to == "ana@school.edu"
    assert "Essay" in msg.subject and "Essay" in msg.text and "Ben" not in msg.text
    assert any("Essay" in m.text for m in env.notifiers[1].sent)  # Telegram still comes

    await env.hub.tick_all()
    assert len(env.outbox.sent) == 1  # once only


async def test_disconnect_erases_the_address(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    await confirmed(env, 1, "me@school.edu")
    user = env.hub.registry.get_user(1)
    assert user is not None
    await env.signup.disconnect(user, confirmed=True)
    assert env.hub.registry.get_user(1) is None


async def test_email_command_handler_replies_in_chat(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    bot = mock_bot()
    await email_cmd(env.signup)(message_update("/email", user_id=1, bot=bot), context())
    assert bot.send_message.await_args.kwargs["text"] == copy.EMAIL_STATUS_OFF


@pytest.mark.parametrize(
    ("address", "school"),
    [
        ("me@uab.edu", True),
        ("me@mail.uab.edu", True),
        ("me@ox.ac.uk", True),
        ("me@unimelb.edu.au", True),
        ("me@district.k12.ca.us", True),
        ("me@gmail.com", False),
        ("me@icloud.com", False),
        ("me@education.com", False),
        ("me@edu.example.com", False),
    ],
)
def test_school_addresses_are_recognised(address: str, school: bool) -> None:
    assert looks_like_school_address(address) is school


async def test_personal_address_gets_no_school_hint(tmp_path: Path) -> None:
    env = build_hub(tmp_path, email=True)
    await sign_up(env, 1)
    assert await email(env, 1, "me@gmail.com") == [
        copy.EMAIL_CODE_SENT.format(address="me@gmail.com")
    ]
