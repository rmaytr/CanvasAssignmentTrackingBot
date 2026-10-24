"""Turn what a friend types during sign-up into checked values. Pure functions."""

from __future__ import annotations

import ipaddress
import re
from datetime import time
from functools import cache
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import available_timezones

from canvas_tracker.config import validate_base_url

_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".arpa")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def normalize_canvas_url(text: str) -> str | None:
    """``https://host`` from a typed address or any Canvas page URL, or None if it can't be
    a public Canvas site (plain http, IPs, credentials, local or internal names)."""
    raw = text.strip()
    if not raw or " " in raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme.lower() != "https" or parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not _HOST_RE.match(host) or host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    try:
        return validate_base_url(f"https://{host}" + (f":{port}" if port else ""))
    except ValueError:
        return None


def is_public_address(address: str) -> bool:
    """True for a globally routable IP; False for loopback, private, link-local and the like,
    so a sign-up can't point the bot at the server it runs on."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


# Common names people type for US zones, plus a few abbreviations.
_ALIASES = {
    "eastern": "America/New_York",
    "et": "America/New_York",
    "est": "America/New_York",
    "edt": "America/New_York",
    "central": "America/Chicago",
    "ct": "America/Chicago",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mountain": "America/Denver",
    "mt": "America/Denver",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "arizona": "America/Phoenix",
    "pacific": "America/Los_Angeles",
    "pt": "America/Los_Angeles",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "alaska": "America/Anchorage",
    "hawaii": "Pacific/Honolulu",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "philadelphia": "America/New_York",
    "washington": "America/New_York",
    "dc": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "pittsburgh": "America/New_York",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "austin": "America/Chicago",
    "minneapolis": "America/Chicago",
    "st louis": "America/Chicago",
    "nashville": "America/Chicago",
    "new orleans": "America/Chicago",
    "salt lake city": "America/Denver",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "uk": "Europe/London",
    "utc": "UTC",
}


@cache
def _zone_index() -> tuple[dict[str, str], dict[str, str]]:
    exact: dict[str, str] = {}
    by_city: dict[str, str] = {}
    for zone in sorted(available_timezones()):
        if "/" not in zone and zone != "UTC":
            continue  # legacy names like "EST" or "PST8PDT" are fixed offsets or obscure
        exact[zone.lower()] = zone
        if "/" in zone and not zone.startswith(("Etc/", "SystemV/")):
            city = zone.rsplit("/", 1)[1].replace("_", " ").lower()
            by_city.setdefault(city, zone)
    return exact, by_city


def resolve_timezone(text: str) -> str | None:
    key = " ".join(text.strip().lower().replace("_", " ").split())
    if not key:
        return None
    for suffix in (" time", " standard time"):
        key = key.removesuffix(suffix)
    if key in _ALIASES:  # before zone names: "EST" is also a legacy fixed-offset zone
        return _ALIASES[key]
    exact, by_city = _zone_index()
    return exact.get(text.strip().lower()) or by_city.get(key)


_CLOCK_RE = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?\s*([ap]\.?m\.?)?$")


def parse_clock(text: str) -> time | None:
    """'8', '8am', '8:30', '7.45 AM', '20:00' → a time; None if it isn't one."""
    match = _CLOCK_RE.match(text.strip().lower())
    if match is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    meridiem = match.group(3)
    if minute > 59:
        return None
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem.startswith("p") else 0)
    elif hour > 23:
        return None
    return time(hour, minute)


_RANGE_RE = re.compile(r"\s*(?:-|\u2013|\u2014|\bto\b|\buntil\b)\s*")


def parse_quiet(text: str) -> tuple[time, time] | Literal["off"] | None:
    """'23:00-07:00', '11pm - 7am', '12 am to 8 am' → (start, end); 'off' → 'off'."""
    value = text.strip().lower()
    if value in ("off", "none", "no", "never"):
        return "off"
    pieces = _RANGE_RE.split(value)
    if len(pieces) != 2:
        return None
    start, end = parse_clock(pieces[0]), parse_clock(pieces[1])
    if start is None or end is None or start == end:
        return None
    return start, end


def quiet_window(stored: str) -> tuple[time, time] | None:
    """The stored quiet-hours text as (start, end), or None when quiet hours are off."""
    parsed = parse_quiet(stored)
    return parsed if isinstance(parsed, tuple) else None


def looks_like_token(text: str) -> bool:
    value = text.strip()
    return 20 <= len(value) <= 200 and " " not in value and value.isascii()
