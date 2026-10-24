"""Entry point.

``python -m canvas_tracker``              run the bot (friends mode)
``python -m canvas_tracker healthcheck``  exit 0 if the tick loop ran in the last 3 minutes
``python -m canvas_tracker genkey``       print a new TOKEN_KEY
"""

from __future__ import annotations

import asyncio
import contextlib
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
    from telegram.error import InvalidToken
    from telegram.ext import Application

    from canvas_tracker.bot.pairing import PairingCode
    from canvas_tracker.config import base_settings, load_config
    from canvas_tracker.hub.handlers import register_handlers
    from canvas_tracker.hub.hub import Hub
    from canvas_tracker.hub.registry import open_registry
    from canvas_tracker.hub.secretbox import SecretBox
    from canvas_tracker.hub.signup import Signup
    from canvas_tracker.notify.telegram import TelegramNotifier
    from canvas_tracker.runtime.logging import configure_logging

    try:
        cfg = load_config()
    except (ValueError, OSError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    bot_token = cfg.telegram_bot_token.get_secret_value()
    configure_logging(cfg.log_level, [bot_token, cfg.token_key.get_secret_value()])
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    registry = open_registry(cfg.data_dir / "registry.db")

    def clock() -> datetime:
        return datetime.now(UTC)

    def announce(code: str) -> None:
        # The pairing code is one-time, expires in 15 minutes and is not a token.
        log.warning("pairing code: send /start %s to your bot", code)

    pairing = PairingCode(now=clock, on_new_code=announce)
    hub = Hub(
        registry=registry,
        box=SecretBox(cfg.token_key.get_secret_value()),
        data_dir=cfg.data_dir,
        shared=base_settings(cfg),
        clock=clock,
        notifier_factory=lambda telegram_id: TelegramNotifier(app.bot, chat_id=lambda: telegram_id),
        item_retention=timedelta(days=cfg.item_retention_days),
        max_users=cfg.max_users,
        owner_env_id=cfg.owner_telegram_id,
        pairing=pairing,
    )
    tasks: dict[str, asyncio.Task[None]] = {}

    async def on_start(application: Any) -> None:
        from telegram import BotCommand
        from telegram.error import TelegramError

        from canvas_tracker.render.copy import BOT_COMMANDS

        with contextlib.suppress(TelegramError):  # only the menu; the bot works without it
            await application.bot.set_my_commands([BotCommand(c, d) for c, d in BOT_COMMANDS])
        hub.load()
        tasks["hub"] = asyncio.create_task(hub.run_forever())
        if hub.owner_id() is None:
            announce(pairing.code)
        log.info("started", extra={"users": len(hub.tenants)})

    async def on_stop(_app: Any) -> None:
        task = tasks.get("hub")
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await hub.close()

    app = Application.builder().token(bot_token).post_init(on_start).post_shutdown(on_stop).build()
    register_handlers(app, Signup(hub))
    try:
        app.run_polling(allowed_updates=["message", "callback_query"])
    except InvalidToken:
        # PTB's message contains the token, so report a fixed one through the redacting log.
        log.error("Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN_FILE.")
        return 2
    except Exception:
        log.exception("the bot stopped unexpectedly")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["healthcheck"]:
        data_dir = Path(os.environ.get("DATA_DIR", "/data"))
        return healthcheck(data_dir / "registry.db")
    if args[:1] == ["genkey"]:
        from canvas_tracker.hub.secretbox import generate_key

        print(generate_key())
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
