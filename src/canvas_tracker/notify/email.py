"""Email delivery over SMTP (any provider: Brevo, Gmail, your own domain…).

Uses the standard library in a worker thread, so a slow mail server never blocks the
bot. Errors become ``NotifyError`` with only the exception class name: SMTP replies
can echo addresses or credentials, so they are never logged.
"""

from __future__ import annotations

import asyncio
import html
import re
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Literal

from canvas_tracker.notify.base import NotifyError
from canvas_tracker.render.message import RenderedMessage

SMTP_TIMEOUT_S = 30.0
_LINK_RE = re.compile(r'<a href="([^"]*)">(.*?)</a>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_EMAIL_RE = re.compile(r"^[^@\s<>()\[\],;:\"\\]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
EMAIL_MAX = 254


def normalize_address(text: str) -> str | None:
    """A plausible single address, lower-cased domain, or None. Rejects anything that
    could smuggle extra headers or recipients (spaces, commas, angle brackets, CR/LF)."""
    value = text.strip()
    if not value or len(value) > EMAIL_MAX or not _EMAIL_RE.match(value):
        return None
    local, _, domain = value.rpartition("@")
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        return None
    return f"{local}@{domain.lower()}"


def to_plain(body: str) -> str:
    """Telegram-style HTML to plain text; links keep their address in brackets."""
    text = _LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", body)
    return html.unescape(_TAG_RE.sub("", text))


def to_html(body: str) -> str:
    lines = body.split("\n")
    inner = "<br>\n".join(lines)
    return (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,Roboto,'
        'Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#1a1a1a">'
        f"{inner}</body></html>"
    )


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    security: Literal["starttls", "tls"]
    username: str | None
    password: str | None
    sender: str  # the From address
    sender_name: str = "Canvas Tracker"


def build_message(cfg: SmtpConfig, to: str, msg: RenderedMessage) -> EmailMessage:
    local, _, domain = cfg.sender.rpartition("@")
    email = EmailMessage()
    email["From"] = Address(cfg.sender_name, local, domain)
    email["To"] = to
    email["Subject"] = msg.subject or cfg.sender_name
    email["Date"] = formatdate(localtime=False)
    email["Message-ID"] = make_msgid(domain=domain or None)
    email["Auto-Submitted"] = "auto-generated"  # no vacation auto-replies
    email.set_content(to_plain(msg.text))
    email.add_alternative(to_html(msg.text), subtype="html")
    return email


class SmtpMailer:
    """A ``Notifier`` that emails one person, whose address is looked up at send time."""

    def __init__(
        self,
        cfg: SmtpConfig,
        to: Callable[[], str | None],
        smtp_factory: Callable[[SmtpConfig], smtplib.SMTP] | None = None,
    ) -> None:
        self._cfg = cfg
        self._to = to
        self._smtp_factory = smtp_factory or _connect

    def _send_sync(self, to: str, msg: RenderedMessage) -> None:
        email = build_message(self._cfg, to, msg)
        with self._smtp_factory(self._cfg) as smtp:
            if self._cfg.username and self._cfg.password:
                smtp.login(self._cfg.username, self._cfg.password)
            smtp.send_message(email)

    async def send(self, msg: RenderedMessage) -> int | None:
        to = self._to()
        if to is None:
            raise NotifyError("NoAddress")
        try:
            await asyncio.to_thread(self._send_sync, to, msg)
        except (smtplib.SMTPException, OSError, ValueError) as exc:
            raise NotifyError(type(exc).__name__) from None
        return None


def _connect(cfg: SmtpConfig) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if cfg.security == "tls":
        return smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_S, context=context)
    smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_S)
    try:
        smtp.starttls(context=context)  # never send a password or mail in the clear
    except BaseException:
        smtp.close()
        raise
    return smtp
