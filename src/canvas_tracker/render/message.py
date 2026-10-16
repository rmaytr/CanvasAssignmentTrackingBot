"""Channel-neutral message types produced by the renderers."""

from __future__ import annotations

from dataclasses import dataclass

MAX_CALLBACK_BYTES = 64


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
