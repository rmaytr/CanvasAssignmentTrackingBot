"""One-time pairing code that links the bot to its owner's Telegram account (PRD §7.6)."""

from __future__ import annotations

import hmac
import random
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
CODE_LENGTH = 8
CODE_LIFETIME = timedelta(minutes=15)
MAX_WRONG = 5


class PairingResult(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    EXPIRED = "expired"
    LOCKED = "locked"


class PairingCode:
    def __init__(
        self,
        now: Callable[[], datetime],
        on_new_code: Callable[[str], None],
        rng: random.Random | None = None,
    ) -> None:
        self._now = now
        self._on_new_code = on_new_code
        self._rng = rng
        self.code = ""
        self.expires_at = now()
        self._wrong = 0
        self._issue()

    def _issue(self) -> None:
        choose = self._rng.choice if self._rng is not None else secrets.choice
        self.code = "".join(choose(ALPHABET) for _ in range(CODE_LENGTH))
        self.expires_at = self._now() + CODE_LIFETIME
        self._wrong = 0

    def _reissue(self) -> None:
        self._issue()
        self._on_new_code(self.code)

    def check(self, attempt: str) -> PairingResult:
        if self._now() >= self.expires_at:
            self._reissue()
            return PairingResult.EXPIRED
        if hmac.compare_digest(attempt.strip().upper().encode(), self.code.encode()):
            self._issue()  # one-time: the used code stops working
            return PairingResult.OK
        self._wrong += 1
        if self._wrong >= MAX_WRONG:
            self._reissue()
            return PairingResult.LOCKED
        return PairingResult.WRONG
