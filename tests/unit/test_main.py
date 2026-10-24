from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canvas_tracker.__main__ import healthcheck, main
from canvas_tracker.hub.registry import HUB_LAST_TICK_AT, open_registry
from canvas_tracker.hub.secretbox import SecretBox, generate_key


def test_healthcheck_fresh_stale_and_missing(tmp_path: Path) -> None:
    db = tmp_path / "registry.db"
    assert healthcheck(db) == 1
    registry = open_registry(db)
    registry.set_time(HUB_LAST_TICK_AT, datetime.now(UTC))
    assert healthcheck(db) == 0
    registry.set_time(HUB_LAST_TICK_AT, datetime.now(UTC) - timedelta(minutes=4))
    assert healthcheck(db) == 1


def test_main_healthcheck_reads_the_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["healthcheck"]) == 1
    open_registry(tmp_path / "registry.db").set_time(HUB_LAST_TICK_AT, datetime.now(UTC))
    assert main(["healthcheck"]) == 0


def test_genkey_prints_a_usable_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["genkey"]) == 0
    key = capsys.readouterr().out.strip()
    SecretBox(key)  # valid
    assert key != generate_key()


def test_bad_config_exits_with_a_readable_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("TOKEN_KEY", "TOKEN_KEY_FILE", "TELEGRAM_BOT_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "y")
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "configuration error" in err and "set TOKEN_KEY or TOKEN_KEY_FILE" in err
    assert "Traceback" not in err


def test_rejected_telegram_token_is_reported_without_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:  # review I6
    import logging

    from telegram.error import InvalidToken
    from telegram.ext import Application

    token = "424242424:SENTINEL_sentinel_SENTINEL_sentinel_00"
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN_FILE", raising=False)
    monkeypatch.delenv("TOKEN_KEY_FILE", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TOKEN_KEY", generate_key())
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def reject(self: object, *args: object, **kwargs: object) -> None:
        raise InvalidToken(f"The token `{token}` was rejected by the server.")

    monkeypatch.setattr(Application, "run_polling", reject)
    try:
        assert main([]) == 2
    finally:
        logging.getLogger().handlers = []
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Telegram rejected the bot token" in output
    assert token not in output and token[-8:] not in output
