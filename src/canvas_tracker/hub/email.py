"""The /email command: add an address (confirmed with a code sent to it), or turn email off.

An address only receives the morning list and deadline emails after its owner types
the 6-digit code from it into Telegram, so nobody can point the bot at someone else's
inbox. Addresses are stored encrypted; codes only as a hash, for 15 minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from canvas_tracker.hub.hub import Hub
from canvas_tracker.hub.registry import User
from canvas_tracker.notify.base import NotifyError
from canvas_tracker.notify.email import normalize_address
from canvas_tracker.render import copy
from canvas_tracker.render.message import RenderedMessage

CODE_DIGITS = 6
CODE_LIFETIME = timedelta(minutes=15)
RESEND_AFTER = timedelta(minutes=1)
MAX_ATTEMPTS = 5
OFF_WORDS = frozenset({"off", "stop", "remove", "delete", "none"})


def _code_hash(telegram_id: int, code: str) -> str:
    return hashlib.sha256(f"{telegram_id}:{code}".encode()).hexdigest()


def _clear_pending() -> dict[str, object]:
    return {
        "email_pending_sealed": None,
        "email_code_hash": None,
        "email_code_expires_at": None,
        "email_code_attempts": 0,
    }


class EmailSetup:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.registry = hub.registry

    @property
    def available(self) -> bool:
        return self.hub.mailer_factory is not None

    def address(self, user: User) -> str | None:
        if user.email_sealed is None:
            return None
        try:
            return self.hub.box.open(user.email_sealed)
        except ValueError:
            return None

    async def command(self, user: User, arg: str | None) -> list[str]:
        if not self.available:
            return [copy.EMAIL_UNAVAILABLE]
        value = (arg or "").strip()
        if not value:
            current = self.address(user)
            if current is None:
                return [copy.EMAIL_STATUS_OFF]
            return [copy.EMAIL_STATUS_ON.format(address=current)]
        if value.lower() in OFF_WORDS:
            return await self._off(user)
        if value.isdigit() and len(value) == CODE_DIGITS:
            return await self._confirm(user, value)
        address = normalize_address(value)
        if address is None:
            return [copy.EMAIL_INVALID]
        return await self._send_code(user, address)

    async def _off(self, user: User) -> list[str]:
        if user.email_sealed is None and user.email_pending_sealed is None:
            return [copy.EMAIL_ALREADY_OFF]
        self.registry.update_user(user.telegram_id, email_sealed=None, **_clear_pending())
        await self.hub.refresh(user.telegram_id)
        return [copy.EMAIL_TURNED_OFF]

    async def _send_code(self, user: User, address: str) -> list[str]:
        now = self.hub.clock()
        sent = user.email_code_sent_at
        if sent is not None and now - sent < RESEND_AFTER:
            return [copy.EMAIL_WAIT]
        factory = self.hub.mailer_factory
        assert factory is not None  # noqa: S101 - checked by command()
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        self.registry.update_user(user.telegram_id, email_code_sent_at=now)
        message = RenderedMessage(
            copy.EMAIL_CODE_BODY.format(code=code),
            subject=copy.EMAIL_CODE_SUBJECT.format(code=code),
        )
        try:
            await factory(lambda: address).send(message)
        except NotifyError:
            return [copy.EMAIL_SEND_FAILED]
        self.registry.update_user(
            user.telegram_id,
            email_pending_sealed=self.hub.box.seal(address),
            email_code_hash=_code_hash(user.telegram_id, code),
            email_code_expires_at=now + CODE_LIFETIME,
            email_code_attempts=0,
        )
        return [copy.EMAIL_CODE_SENT.format(address=address)]

    async def _confirm(self, user: User, code: str) -> list[str]:
        if user.email_pending_sealed is None or user.email_code_hash is None:
            return [copy.EMAIL_NO_PENDING]
        expires = user.email_code_expires_at
        if expires is None or self.hub.clock() >= expires:
            self.registry.update_user(user.telegram_id, **_clear_pending())
            return [copy.EMAIL_CODE_EXPIRED]
        if user.email_code_attempts >= MAX_ATTEMPTS:
            self.registry.update_user(user.telegram_id, **_clear_pending())
            return [copy.EMAIL_CODE_LOCKED]
        if not hmac.compare_digest(_code_hash(user.telegram_id, code), user.email_code_hash):
            attempts = user.email_code_attempts + 1
            if attempts >= MAX_ATTEMPTS:
                self.registry.update_user(user.telegram_id, **_clear_pending())
                return [copy.EMAIL_CODE_LOCKED]
            self.registry.update_user(user.telegram_id, email_code_attempts=attempts)
            return [copy.EMAIL_CODE_WRONG]
        self.registry.update_user(
            user.telegram_id, email_sealed=user.email_pending_sealed, **_clear_pending()
        )
        await self.hub.refresh(user.telegram_id)
        updated = self.registry.get_user(user.telegram_id)
        address = self.address(updated) if updated is not None else None
        return [copy.EMAIL_VERIFIED.format(address=address or "")]
