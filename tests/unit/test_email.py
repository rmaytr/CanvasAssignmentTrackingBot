import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from canvas_tracker.config import load_config, smtp_config
from canvas_tracker.domain.models import Send, SendKind
from canvas_tracker.hub.secretbox import generate_key
from canvas_tracker.notify.base import NotifyError
from canvas_tracker.notify.email import (
    SmtpConfig,
    SmtpMailer,
    build_message,
    normalize_address,
    to_plain,
)
from canvas_tracker.render import copy
from canvas_tracker.render.email import render_email
from canvas_tracker.render.format import clean_subject
from canvas_tracker.render.message import RenderedMessage
from tests.factories import NOW, make_item, make_settings, make_snapshot

CFG = SmtpConfig(
    host="smtp.example.com",
    port=587,
    security="starttls",
    username="user",
    password="pw-secret",
    sender="bot@example.com",
)


class FakeSmtp:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.logins: list[tuple[str, str]] = []
        self.sent: list[EmailMessage] = []

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.logins.append((user, password))

    def send_message(self, msg: EmailMessage) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(msg)


# --- addresses ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  me@School.EDU ", "me@school.edu"),
        ("first.last+tag@uni.ac.uk", "first.last+tag@uni.ac.uk"),
        ("no-at-sign", None),
        ("a@localhost", None),
        ("a b@c.com", None),
        ("a@b.com\nBcc: x@y.com", None),
        ("a@b.com,c@d.com", None),
        ("Name <a@b.com>", None),
        (".a@b.com", None),
        ("a..b@c.com", None),
        ("x" * 65 + "@b.com", None),
    ],
)
def test_normalize_address(text: str, expected: str | None) -> None:
    assert normalize_address(text) == expected


# --- message building ----------------------------------------------------------


def test_html_body_becomes_plain_text_with_links() -> None:
    body = 'CS 101 · <a href="https://c.edu/a/1">Essay &amp; notes</a>\n<b>bold</b>'
    assert to_plain(body) == "CS 101 · Essay & notes (https://c.edu/a/1)\nbold"


def test_built_message_has_text_and_html_parts() -> None:
    msg = RenderedMessage('<a href="https://c.edu/x">Lab</a>\nline 2', subject="Hi")
    email = build_message(CFG, "me@school.edu", msg)
    assert email["To"] == "me@school.edu"
    assert email["Subject"] == "Hi"
    assert "bot@example.com" in email["From"]
    assert email["Auto-Submitted"] == "auto-generated"
    plain = email.get_body(("plain",))
    html = email.get_body(("html",))
    assert plain is not None and "Lab (https://c.edu/x)" in plain.get_content()
    assert html is not None and '<a href="https://c.edu/x">Lab</a><br>' in html.get_content()


def test_clean_subject_is_one_short_line() -> None:
    assert clean_subject("a\r\nBcc: x\tb") == "a Bcc: x b"
    assert len(clean_subject("x" * 500)) == 150


# --- delivery -------------------------------------------------------------------


async def test_mailer_logs_in_and_sends() -> None:
    smtp = FakeSmtp()
    mailer = SmtpMailer(CFG, lambda: "me@school.edu", smtp_factory=lambda _c: smtp)  # type: ignore[arg-type,return-value]
    assert await mailer.send(RenderedMessage("hello", subject="S")) is None
    assert smtp.logins == [("user", "pw-secret")]
    [sent] = smtp.sent
    assert sent["To"] == "me@school.edu"


async def test_mailer_errors_never_carry_server_text() -> None:
    error = smtplib.SMTPAuthenticationError(535, b"bad password pw-secret for user")
    smtp = FakeSmtp(fail=error)
    mailer = SmtpMailer(CFG, lambda: "me@school.edu", smtp_factory=lambda _c: smtp)  # type: ignore[arg-type,return-value]
    with pytest.raises(NotifyError) as info:
        await mailer.send(RenderedMessage("hello"))
    assert str(info.value) == "SMTPAuthenticationError"


async def test_mailer_without_an_address_fails() -> None:
    mailer = SmtpMailer(CFG, lambda: None, smtp_factory=lambda _c: FakeSmtp())  # type: ignore[arg-type,return-value]
    with pytest.raises(NotifyError):
        await mailer.send(RenderedMessage("hello"))


# --- rendering -------------------------------------------------------------------

NYZ = ZoneInfo("America/New_York")
DUE = datetime(2026, 10, 20, 23, 59, tzinfo=NYZ).astimezone(UTC)
AT = DUE - timedelta(hours=2)


def test_deadline_email_for_one_item() -> None:
    item = make_item(due_at=DUE, title="Essay\n draft", course_name="CS 101")
    send = Send("email:due:x", SendKind.EMAIL_DEADLINE, (item.ref,))
    msg = render_email(send, make_snapshot([item], last_successful_sync_at=AT), AT, make_settings())
    assert msg is not None
    assert msg.subject == "⏰ Due at 11:59 PM: Essay draft"
    assert "CS 101 · Essay draft" in msg.text
    assert copy.EMAIL_FOOTER in msg.text


def test_deadline_email_combines_items_due_together() -> None:
    a = make_item(due_at=DUE, title="Essay")
    b = make_item(due_at=DUE, title="Quiz")
    send = Send("email:due:x", SendKind.EMAIL_DEADLINE, (a.ref, b.ref))
    msg = render_email(send, make_snapshot([a, b], last_successful_sync_at=AT), AT, make_settings())
    assert msg is not None
    assert msg.subject == "⏰ 2 assignments due at 11:59 PM"
    assert "Essay" in msg.text and "Quiz" in msg.text


def test_deadline_email_mentions_stale_data() -> None:
    item = make_item(due_at=DUE)
    send = Send("email:due:x", SendKind.EMAIL_DEADLINE, (item.ref,))
    msg = render_email(send, make_snapshot([item]), AT, make_settings(), stale=True)
    assert msg is not None and "⚠️" in msg.text


def test_deadline_email_for_vanished_items_is_skipped() -> None:
    send = Send("email:due:x", SendKind.EMAIL_DEADLINE, ("assignment-999",))
    assert render_email(send, make_snapshot([]), AT, make_settings()) is None


def test_digest_email_has_a_dated_subject() -> None:
    item = make_item(due_in=timedelta(hours=10))
    send = Send("email:digest:2026-10-20", SendKind.EMAIL_DIGEST, (item.ref,))
    msg = render_email(send, make_snapshot([item]), NOW, make_settings())
    assert msg is not None
    assert msg.subject == "☀️ Your list for Tue Oct 20"
    assert "Homework" in msg.text


# --- config ------------------------------------------------------------------------

BASE = {"TELEGRAM_BOT_TOKEN": "1:a", "TOKEN_KEY": generate_key()}


def test_email_is_off_by_default() -> None:
    assert smtp_config(load_config(BASE)) is None
    assert smtp_config(load_config({**BASE, "SMTP_HOST": " "})) is None


def test_full_smtp_config(tmp_path: Any) -> None:
    secret = tmp_path / "smtp_password"
    secret.write_text("pw-secret\n")
    cfg = load_config(
        {
            **BASE,
            "SMTP_HOST": "smtp-relay.brevo.com",
            "SMTP_PORT": "465",
            "SMTP_SECURITY": "TLS",
            "SMTP_USERNAME": "user",
            "SMTP_PASSWORD_FILE": str(secret),
            "EMAIL_FROM": "bot@example.com",
        }
    )
    smtp = smtp_config(cfg)
    assert smtp is not None
    assert (smtp.host, smtp.port, smtp.security, smtp.password) == (
        "smtp-relay.brevo.com",
        465,
        "tls",
        "pw-secret",
    )
    assert "pw-secret" not in repr(cfg)


@pytest.mark.parametrize(
    ("extra", "problem"),
    [
        ({"SMTP_HOST": "h"}, "EMAIL_FROM is required"),
        ({"SMTP_HOST": "h", "EMAIL_FROM": "not an address"}, "EMAIL_FROM"),
        ({"SMTP_HOST": "h", "EMAIL_FROM": "a@b.com", "SMTP_USERNAME": "u"}, "SMTP_PASSWORD"),
        ({"SMTP_HOST": "h", "EMAIL_FROM": "a@b.com", "SMTP_SECURITY": "none"}, "SMTP_SECURITY"),
    ],
)
def test_bad_smtp_config(extra: dict[str, str], problem: str) -> None:
    with pytest.raises(ValueError, match=problem) as info:
        load_config({**BASE, **extra})
    assert "pw" not in str(info.value)


def test_empty_password_file_means_no_password(tmp_path: Any) -> None:
    empty = tmp_path / "smtp_password.txt"
    empty.write_text("\n")
    cfg = load_config({**BASE, "SMTP_PASSWORD_FILE": str(empty)})
    assert cfg.smtp_password is None and smtp_config(cfg) is None
    missing = load_config({**BASE, "SMTP_PASSWORD_FILE": str(tmp_path / "nope.txt")})
    assert missing.smtp_password is None


def test_env_example_smtp_lines_load(tmp_path: Any) -> None:
    from pathlib import Path

    lines = Path(".env.example").read_text().splitlines()
    env = dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))
    empty = tmp_path / "smtp_password.txt"
    empty.write_text("")
    cfg = load_config({**BASE, **env, "SMTP_PASSWORD_FILE": str(empty)})
    assert smtp_config(cfg) is None
