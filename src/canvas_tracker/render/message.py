"""Channel-neutral message types produced by the renderers."""

from __future__ import annotations

from dataclasses import dataclass

MAX_CALLBACK_BYTES = 64
# Item buttons: "<action>:<item id>[:<salt>]", e.g. "d:42:9f3a0c1b". The salt is the
# database's own (Snapshot.button_salt); older buttons have none. bot/callbacks.py and
# hub/handlers.py match against this one pattern.
ITEM_CALLBACK_PATTERN = r"^([dsux]):(\d+)(?::([0-9a-f]{8}))?$"


def item_callback(action: str, db_id: int, salt: str = "") -> str:
    return f"{action}:{db_id}:{salt}" if salt else f"{action}:{db_id}"


@dataclass(frozen=True, slots=True)
class Button:
    label: str
    callback_data: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        if (self.callback_data is None) == (self.url is None):
            raise ValueError("a button needs exactly one of callback_data or url")
        if (
            self.callback_data is not None
            and len(self.callback_data.encode("utf-8")) > MAX_CALLBACK_BYTES
        ):
            raise ValueError("callback_data is limited to 64 bytes")


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    text: str
    keyboard: tuple[tuple[Button, ...], ...] = ()
    subject: str = ""  # email only; Telegram ignores it
