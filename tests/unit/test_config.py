from datetime import time, timedelta
from pathlib import Path

import pytest

from canvas_tracker.config import (
    hidden_courses,
    load_config,
    to_settings,
    token_provider,
    validate_base_url,
)

BASE_ENV = {
    "CANVAS_BASE_URL": "https://canvas.example.edu",
    "CANVAS_TOKEN": "1234~abc",
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "TIMEZONE": "America/New_York",
}


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


def test_defaults_and_settings_mapping() -> None:
    cfg = load_config(env())
    s = to_settings(cfg)
    assert (s.tz, s.digest_time, s.digest_grace_until) == ("America/New_York", time(8), time(12))
    assert (s.quiet_start, s.quiet_end) == (time(0), time(8))
    assert s.reminder_interval == timedelta(minutes=120)
    assert s.reminder_window == timedelta(hours=24)
    assert s.digest_lookahead == timedelta(days=14)
    assert s.overdue_reminder_max == timedelta(hours=48)
    assert s.canvas_host == "canvas.example.edu"
    assert cfg.db_path == Path("/data/bot.db") and cfg.item_retention_days == 30


def test_secret_file_is_stripped(tmp_path: Path) -> None:  # Review Focus 5
    f = tmp_path / "canvas_token"
    f.write_text("  abc123\n")
    cfg = load_config(env(CANVAS_TOKEN="__unset__", CANVAS_TOKEN_FILE=str(f)))
    assert cfg.canvas_token.get_secret_value() == "abc123"


def test_empty_secret_file_fails_clearly(tmp_path: Path) -> None:
    f = tmp_path / "canvas_token"
    f.write_text("\n")
    with pytest.raises(ValueError, match="CANVAS_TOKEN_FILE is empty"):
        load_config(env(CANVAS_TOKEN="__unset__", CANVAS_TOKEN_FILE=str(f)))


def test_both_secret_forms_fail(tmp_path: Path) -> None:
    f = tmp_path / "t"
    f.write_text("x")
    with pytest.raises(ValueError, match="set CANVAS_TOKEN or CANVAS_TOKEN_FILE, not both"):
        load_config(env(CANVAS_TOKEN_FILE=str(f)))


def test_missing_secret_names_both_forms() -> None:
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_FILE"):
        load_config(env(TELEGRAM_BOT_TOKEN="__unset__"))


def test_rejects_bad_values() -> None:
    with pytest.raises(ValueError):
        load_config(env(REMINDER_INTERVAL_MINUTES="29"))
    with pytest.raises(ValueError):
        load_config(env(TIMEZONE="Mars/Olympus"))
    with pytest.raises(ValueError, match=r"DATA_MODE=ical arrives in v1\.0 \(M2\)"):
        load_config(env(DATA_MODE="ical"))
    with pytest.raises(ValueError):
        load_config(env(QUIET_HOURS="25:00-08:00"))
    with pytest.raises(ValueError):
        load_config(env(CANVAS_BASE_URL="http://canvas.example.edu"))


def test_quiet_hours_off() -> None:
    s = to_settings(load_config(env(QUIET_HOURS="off")))
    assert s.quiet_start is None and s.quiet_end is None


def test_repr_hides_tokens() -> None:
    cfg = load_config(env())
    assert "1234~abc" not in repr(cfg) and "123:abc" not in repr(cfg)


def test_token_provider_rereads_file(tmp_path: Path) -> None:
    f = tmp_path / "canvas_token"
    f.write_text("first\n")
    e = env(CANVAS_TOKEN="__unset__", CANVAS_TOKEN_FILE=str(f))
    provider = token_provider(load_config(e), e)
    assert provider() == "first"
    f.write_text("second\n")
    assert provider() == "second"


def test_token_provider_uses_env_value_without_file() -> None:
    e = env()
    assert token_provider(load_config(e), e)() == "1234~abc"


def test_hidden_courses() -> None:
    cfg = load_config(env(HIDE_COURSES=" PE 100, 4521 ,,"))
    assert hidden_courses(cfg) == frozenset({"PE 100", "4521"})
