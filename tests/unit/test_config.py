from datetime import timedelta
from pathlib import Path

import pytest

from canvas_tracker.config import base_settings, load_config, validate_base_url
from canvas_tracker.hub.secretbox import generate_key

KEY = generate_key()
BASE_ENV = {"TELEGRAM_BOT_TOKEN": "123:abc", "TOKEN_KEY": KEY}


def env(**overrides: str) -> dict[str, str]:
    merged = {**BASE_ENV, **overrides}
    return {k: v for k, v in merged.items() if v != "__unset__"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://Canvas.School.edu/", "https://canvas.school.edu"),
        ("https://canvas.school.edu", "https://canvas.school.edu"),
        ("https://canvas.school.edu:8443", "https://canvas.school.edu:8443"),
    ],
)
def test_validate_base_url_accepts(url: str, expected: str) -> None:
    assert validate_base_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://canvas.school.edu",
        "https://u:p@canvas.school.edu",
        "https://1.2.3.4",
        "https://[::1]",
        "https://canvas.school.edu/path",
        "https://canvas.school.edu?q=1",
        "https://canvas.school.edu#frag",
        "canvas.school.edu",
    ],
)
def test_validate_base_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_defaults() -> None:
    cfg = load_config(env())
    assert cfg.data_dir == Path("/data")
    assert cfg.max_users == 25 and cfg.owner_telegram_id is None
    s = base_settings(cfg)
    assert s["reminder_interval"] == timedelta(minutes=120)
    assert s["reminder_window"] == timedelta(hours=24)
    assert s["digest_lookahead"] == timedelta(days=14)
    assert s["overdue_reminder_max"] == timedelta(hours=48)


def test_secret_file_is_stripped(tmp_path: Path) -> None:
    f = tmp_path / "key"
    f.write_text(f"  {KEY}\n")
    cfg = load_config(env(TOKEN_KEY="__unset__", TOKEN_KEY_FILE=str(f)))
    assert cfg.token_key.get_secret_value() == KEY


def test_empty_secret_file_fails_clearly(tmp_path: Path) -> None:
    f = tmp_path / "key"
    f.write_text("\n")
    with pytest.raises(ValueError, match="TOKEN_KEY_FILE is empty"):
        load_config(env(TOKEN_KEY="__unset__", TOKEN_KEY_FILE=str(f)))


def test_both_secret_forms_fail(tmp_path: Path) -> None:
    f = tmp_path / "t"
    f.write_text("x")
    with pytest.raises(ValueError, match="set TOKEN_KEY or TOKEN_KEY_FILE, not both"):
        load_config(env(TOKEN_KEY_FILE=str(f)))


def test_missing_secret_names_both_forms() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_FILE"):
        load_config(env(TELEGRAM_BOT_TOKEN="__unset__"))


def test_bad_key_is_rejected_without_echoing_it() -> None:
    with pytest.raises(ValueError, match="TOKEN_KEY") as info:
        load_config(env(TOKEN_KEY="definitely-not-a-key"))
    assert "definitely-not-a-key" not in str(info.value)


def test_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        load_config(env(REMINDER_INTERVAL_MINUTES="29"))
    with pytest.raises(ValueError):
        load_config(env(MAX_USERS="0"))
    with pytest.raises(ValueError, match="OWNER_TELEGRAM_ID"):
        load_config(env(OWNER_TELEGRAM_ID="me"))


def test_empty_owner_means_pairing() -> None:
    assert load_config(env(OWNER_TELEGRAM_ID="")).owner_telegram_id is None
    assert load_config(env(OWNER_TELEGRAM_ID=" 42 ")).owner_telegram_id == 42


def test_repr_hides_secrets() -> None:
    cfg = load_config(env())
    assert KEY not in repr(cfg) and "123:abc" not in repr(cfg)


def test_permission_error_names_the_fix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "key"
    f.write_text(KEY)

    def deny(*_args: object, **_kwargs: object) -> str:
        raise PermissionError

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(ValueError, match="10001"):
        load_config(env(TOKEN_KEY="__unset__", TOKEN_KEY_FILE=str(f)))
