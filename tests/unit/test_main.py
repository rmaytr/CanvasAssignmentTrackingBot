from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from canvas_tracker.__main__ import healthcheck, main
from canvas_tracker.store.repo import LAST_TICK_AT
from tests.store_helpers import new_store


def test_healthcheck_fresh_stale_and_missing(tmp_path: Path) -> None:
    db = tmp_path / "bot.db"
    assert healthcheck(db) == 1
    store = new_store(db)
    store.set_time(LAST_TICK_AT, datetime.now(UTC))
    assert healthcheck(db) == 0
    store.set_time(LAST_TICK_AT, datetime.now(UTC) - timedelta(minutes=4))
    assert healthcheck(db) == 1


def test_main_healthcheck_needs_no_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "missing.db"))
    assert main(["healthcheck"]) == 1


def test_bad_config_exits_with_a_readable_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("CANVAS_TOKEN", "CANVAS_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CANVAS_BASE_URL", "https://canvas.example.edu")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "y")
    monkeypatch.setenv("TIMEZONE", "America/New_York")
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "configuration error" in err and "set CANVAS_TOKEN or CANVAS_TOKEN_FILE" in err
    assert "Traceback" not in err
