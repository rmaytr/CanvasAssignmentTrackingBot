"""Notifier interface and an in-memory fake for tests."""

from __future__ import annotations

from typing import Protocol

from canvas_tracker.render.message import RenderedMessage


class NotifyError(Exception):
    """Delivery failed. The message is only the error class name, never request details."""


class NotPairedError(NotifyError):
    """No owner has been paired yet, so there is nobody to send to."""


class Notifier(Protocol):
    async def send(self, msg: RenderedMessage) -> int | None:
        """Deliver one message; return its channel message ID if there is one."""
        ...


class FakeNotifier:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[RenderedMessage] = []
        self.fail_times = fail_times
        self._next_id = 0

    async def send(self, msg: RenderedMessage) -> int | None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise NotifyError("FakeFailure")
        self.sent.append(msg)
        self._next_id += 1
        return self._next_id
