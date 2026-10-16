"""Committed fixtures must never contain tokens, emails or a real school host."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parents[1] / "fixtures"
TOKEN_RE = re.compile(r"\d{1,6}~[A-Za-z0-9]{20,}")
TELEGRAM_RE = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOST_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
ALLOWED_HOSTS = {"canvas.example.edu"}
ALLOWED_EMAILS = {"user@example.edu"}

FILES = sorted(p for p in FIXTURES.rglob("*") if p.is_file())


@pytest.mark.parametrize("path", FILES, ids=[str(p.relative_to(FIXTURES)) for p in FILES])
def test_fixture_is_scrubbed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not TOKEN_RE.search(text), "Canvas token in fixture"
    assert not TELEGRAM_RE.search(text), "Telegram token in fixture"
    assert set(EMAIL_RE.findall(text)) <= ALLOWED_EMAILS, "email address in fixture"
    assert set(HOST_RE.findall(text)) <= ALLOWED_HOSTS, "real host in fixture"
