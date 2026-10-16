"""Entry point: ``python -m canvas_tracker`` runs the bot; ``... healthcheck`` checks it."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HEALTH_MAX_AGE = timedelta(minutes=3)
log = logging.getLogger("canvas_tracker")


def healthcheck(db_path: Path) -> int:
    """0 if the tick loop ran in the last 3 minutes, else 1. Opens the database read-only."""
    if not db_path.exists():
        return 1
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM state WHERE key = 'last_tick_at'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 1
    if row is None or row[0] is None:
        return 1
    from canvas_tracker.store.repo import from_db

    last = from_db(row[0])
    return 0 if last is not None and datetime.now(UTC) - last <= HEALTH_MAX_AGE else 1


def run() -> int:
    os.environ.setdefault("PTB_TIMEDELTA", "1")
    from telegram.ext import Application

    from canvas_tracker.bot.commands import register_handlers
    from canvas_tracker.bot.deps import BotDeps
    from canvas_tracker.bot.gate import owner_id
    from canvas_tracker.bot.pairing import PairingCode
    from canvas_tracker.config import hidden_courses, load_config, to_settings, token_provider
    from canvas_tracker.notify.telegram import TelegramNotifier
    from canvas_tracker.runtime.logging import configure_logging
    from canvas_tracker.runtime.loop import Runtime
    from canvas_tracker.runtime.sync import SyncService
    from canvas_tracker.sources.canvas_client import CanvasClient
    from canvas_tracker.store.db import connect, migrate
    from canvas_tracker.store.repo import Store

    try:
        cfg = load_config()
    except (ValueError, OSError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    secrets = [cfg.canvas_token.get_secret_value(), cfg.telegram_bot_token.get_secret_value()]
    configure_logging(cfg.log_level, secrets)
    conn = connect(cfg.db_path)
    migrate(conn)
    store = Store(conn)
    settings = to_settings(cfg)
    token = token_provider(cfg)
    client = CanvasClient(cfg.canvas_base_url, token)
    sync = SyncService(client, store, cfg.canvas_base_url)

    def clock() -> datetime:
        return datetime.now(UTC)

    def announce(code: str) -> None:
        # The pairing code is one-time, expires in 15 minutes and is not a token.
        log.warning("pairing code: send /start %s to your bot", code)

    pairing = PairingCode(now=clock, on_new_code=announce)
    tasks: dict[str, asyncio.Task[None]] = {}

    async def on_start(_app: Any) -> None:
        tasks["runtime"] = asyncio.create_task(runtime.run_forever())
        if owner_id(deps) is None:
            announce(pairing.code)

    async def on_stop(_app: Any) -> None:
        task = tasks.get("runtime")
        if task is not None:
            task.cancel()
        await client.aclose()

    app = (
        Application.builder()
        .token(cfg.telegram_bot_token.get_secret_value())
        .post_init(on_start)
        .post_shutdown(on_stop)
        .build()
    )
    deps = BotDeps(
        store=store,
        settings=settings,
        clock=clock,
        sync=sync,
        pairing=pairing,
        env_owner_id=cfg.telegram_owner_id,
        hidden_courses=hidden_courses(cfg),
    )
    runtime = Runtime(
        store=store,
        sync=sync,
        notifier=TelegramNotifier(app.bot, chat_id=lambda: owner_id(deps)),
        settings=settings,
        clock=clock,
        can_send=lambda: owner_id(deps) is not None,
        token=token,
        hidden_courses=deps.hidden_courses,
        item_retention=timedelta(days=cfg.item_retention_days),
    )
    register_handlers(app, deps)
    log.info("starting", extra={"canvas_host": settings.canvas_host, "tz": settings.tz})
    app.run_polling(allowed_updates=["message", "callback_query"])
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["healthcheck"]:
        return healthcheck(Path(os.environ.get("DB_PATH", "/data/bot.db")))
    return run()


if __name__ == "__main__":
    sys.exit(main())
