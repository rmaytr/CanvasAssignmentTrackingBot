"""End to end: sentinel secrets never reach logs, messages or the database (PRD §10.2)."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from canvas_tracker.runtime.logging import configure_logging
from tests.factories import make_settings
from tests.integration.sim_env import ScenarioItem, build_env, ny

CANVAS_SENTINEL = "4242~SENTINELsentinelSENTINELsentinel00"
TELEGRAM_SENTINEL = "424242424:SENTINEL_sentinel_SENTINEL_sentinel_00"


async def test_secrets_never_leak(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", [CANVAS_SENTINEL, TELEGRAM_SENTINEL])
    logging.getLogger("httpx").setLevel(logging.DEBUG)  # worst case: request logging on
    logging.getLogger("httpcore").setLevel(logging.DEBUG)
    try:
        start = ny(10, 20, 9, 0)
        item = ScenarioItem(1, "Essay", lambda _t: start + timedelta(hours=6))
        env = build_env(tmp_path, [item], make_settings(), start, token=CANVAS_SENTINEL)
        echo = f'{{"errors":[{{"message":"bad token {CANVAS_SENTINEL}"}}]}}'
        planner = env.router.routes["planner"]
        for n in range(30):
            if n == 10:
                planner.side_effect = None
                planner.return_value = httpx.Response(401, text=echo)
            elif n == 20:
                planner.return_value = httpx.Response(503, text=echo)
            await env.runtime.tick()
            env.clock.now += timedelta(minutes=11)
        # PTB/httpx would log the Bot API URL, which contains the token
        logging.getLogger("httpx").info(
            "HTTP Request: POST https://api.telegram.org/bot%s/sendMessage", TELEGRAM_SENTINEL
        )
        logging.getLogger("canvas_tracker").error("crash with %s", CANVAS_SENTINEL)
    finally:
        logging.getLogger().handlers = []
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    out = capsys.readouterr().out
    assert "HTTP Request" in out  # the logs really were captured
    for sentinel in (CANVAS_SENTINEL, TELEGRAM_SENTINEL):
        assert sentinel not in out
        assert all(sentinel not in m.text for m in env.notifier.sent)
        for name in ("bot.db", "bot.db-wal"):
            path = tmp_path / name
            if path.exists():
                assert sentinel.encode() not in path.read_bytes()
    assert env.notifier.sent, "the scenario sent messages"
