"""M0 spike: check Telegram behaviour the bot relies on (S8). Owner-only.

Sends test messages to your own chat: HTML escaping, the 4,096-character limit,
silent messages, and editing a keyboard after a button press. The bot token is
read from a file and never printed.

Usage: uv run python spike/probe_telegram.py --token-file ~/tg_token.txt --chat-id 123456
"""

from __future__ import annotations

import argparse
import html
import time
from pathlib import Path
from typing import Any

import httpx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token-file", required=True, type=Path)
    ap.add_argument("--chat-id", required=True, type=int)
    args = ap.parse_args()
    token = args.token_file.expanduser().read_text(encoding="utf-8").strip()
    base = f"https://api.telegram.org/bot{token}"

    def call(method: str, **payload: Any) -> dict[str, Any]:
        r = httpx.post(f"{base}/{method}", json=payload, timeout=40)
        body: dict[str, Any] = r.json()
        print(f"{method:<26} ok={body.get('ok')} {body.get('description', '')}")
        return body

    tricky = html.escape('<b>CS 101</b> & "Quiz" *_[]()~ ✅ مرحبا', quote=True)
    call(
        "sendMessage",
        chat_id=args.chat_id,
        text=f"<b>Escaping test</b>\n{tricky}",
        parse_mode="HTML",
    )
    call("sendMessage", chat_id=args.chat_id, text="x" * 4096)
    call("sendMessage", chat_id=args.chat_id, text="x" * 4097)  # expected: ok=False
    call("sendMessage", chat_id=args.chat_id, text="Silent test", disable_notification=True)
    sent = call(
        "sendMessage",
        chat_id=args.chat_id,
        text="Press the button within 60 s",
        reply_markup={"inline_keyboard": [[{"text": "✅ Done 1", "callback_data": "d:1"}]]},
    )
    message_id = sent.get("result", {}).get("message_id")
    offset = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        updates = call("getUpdates", timeout=20, offset=offset, allowed_updates=["callback_query"])
        for upd in updates.get("result", []):
            offset = upd["update_id"] + 1
            cq = upd.get("callback_query")
            if cq:
                call("answerCallbackQuery", callback_query_id=cq["id"], text="Marked done")
                call(
                    "editMessageReplyMarkup",
                    chat_id=args.chat_id,
                    message_id=message_id,
                    reply_markup={
                        "inline_keyboard": [[{"text": "✔️ 1 done · ↩️ Undo", "callback_data": "u:1"}]]
                    },
                )
                return
    print("No button press received.")


if __name__ == "__main__":
    main()
