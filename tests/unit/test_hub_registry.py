from datetime import time, timedelta
from pathlib import Path

import pytest

from canvas_tracker.hub.registry import INVITE_LIFETIME, Registry, open_registry
from tests.factories import NOW


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    return open_registry(tmp_path / "registry.db")


def test_new_user_starts_signup_at_the_canvas_step(reg: Registry) -> None:
    user = reg.create_user(5, "Ana", now=NOW)
    assert user.status == "onboarding" and user.step == "url"
    assert reg.get_user(5) == user
    assert reg.get_user(6) is None
    assert not user.is_owner


def test_update_and_activate(reg: Registry) -> None:
    reg.create_user(5, "Ana", now=NOW, is_owner=True)
    reg.update_user(
        5,
        canvas_base_url="https://canvas.school.edu",
        token_sealed=b"sealed",
        tz="America/Chicago",
        digest_time=time(7, 30),
        quiet="23:00-07:00",
        status="active",
        step=None,
    )
    user = reg.get_user(5)
    assert user is not None
    assert user.status == "active" and user.step is None and user.is_owner
    assert user.digest_time == time(7, 30) and user.tz == "America/Chicago"
    assert user.token_sealed == b"sealed"
    assert [u.telegram_id for u in reg.active_users()] == [5]


def test_update_rejects_unknown_fields(reg: Registry) -> None:
    reg.create_user(5, "Ana", now=NOW)
    with pytest.raises(ValueError, match="unknown"):
        reg.update_user(5, telegram_id=6)


def test_delete_user(reg: Registry) -> None:
    reg.create_user(5, "Ana", now=NOW)
    reg.delete_user(5)
    assert reg.get_user(5) is None
    assert reg.count_users() == 0


def test_invite_is_one_time_and_expires(reg: Registry) -> None:
    code = reg.create_invite(NOW)
    assert len(code) >= 16 and code.replace("-", "").replace("_", "").isalnum()
    assert code not in str(reg.conn.execute("SELECT * FROM invites").fetchall()[0][0])
    assert reg.redeem_invite(code, 9, NOW + timedelta(days=1))
    assert not reg.redeem_invite(code, 10, NOW + timedelta(days=1))
    late = reg.create_invite(NOW)
    assert not reg.redeem_invite(late, 11, NOW + INVITE_LIFETIME + timedelta(seconds=1))
    assert not reg.redeem_invite("nonsense", 12, NOW)


def test_state(reg: Registry) -> None:
    assert reg.get_state("owner_telegram_id") is None
    reg.set_state("owner_telegram_id", "5")
    assert reg.get_state("owner_telegram_id") == "5"
