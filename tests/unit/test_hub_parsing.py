from datetime import time

import pytest

from canvas_tracker.hub.parsing import (
    is_public_address,
    looks_like_token,
    normalize_canvas_url,
    parse_clock,
    parse_quiet,
    resolve_timezone,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("school.instructure.com", "https://school.instructure.com"),
        ("https://canvas.school.edu/", "https://canvas.school.edu"),
        ("  HTTPS://Canvas.School.edu/courses/12/assignments?x=1  ", "https://canvas.school.edu"),
        ("canvas.school.edu/login/canvas", "https://canvas.school.edu"),
    ],
)
def test_canvas_url_keeps_only_the_https_host(text: str, expected: str) -> None:
    assert normalize_canvas_url(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello",
        "http://canvas.school.edu",
        "localhost",
        "https://10.0.0.5",
        "metadata.google.internal",
        "printer.local",
        "https://user:pw@canvas.school.edu",
        "canvas school edu",
    ],
)
def test_canvas_url_rejects_non_canvas_looking_input(text: str) -> None:
    assert normalize_canvas_url(text) is None


def test_public_address_check() -> None:
    assert is_public_address("8.8.8.8")
    for private in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "169.254.169.254", "::1", "fd00::1"):
        assert not is_public_address(private)


@pytest.mark.parametrize(
    ("text", "zone"),
    [
        ("America/Chicago", "America/Chicago"),
        ("america/chicago", "America/Chicago"),
        ("Chicago", "America/Chicago"),
        ("new york", "America/New_York"),
        ("Pacific", "America/Los_Angeles"),
        ("EST", "America/New_York"),
        ("mountain time", "America/Denver"),
        ("Berlin", "Europe/Berlin"),
        ("Seattle", "America/Los_Angeles"),
    ],
)
def test_resolve_timezone(text: str, zone: str) -> None:
    assert resolve_timezone(text) == zone


def test_resolve_timezone_unknown() -> None:
    assert resolve_timezone("Narnia") is None
    assert resolve_timezone("") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8", time(8, 0)),
        ("8am", time(8, 0)),
        ("8:30", time(8, 30)),
        ("7.45 AM", time(7, 45)),
        ("8:30 pm", time(20, 30)),
        ("12 am", time(0, 0)),
        ("12pm", time(12, 0)),
        ("20:00", time(20, 0)),
    ],
)
def test_parse_clock(text: str, expected: time) -> None:
    assert parse_clock(text) == expected


@pytest.mark.parametrize("text", ["", "25:00", "8:75", "13pm", "noonish", "0am"])
def test_parse_clock_rejects(text: str) -> None:
    assert parse_clock(text) is None


def test_parse_quiet() -> None:
    assert parse_quiet("23:00-07:00") == (time(23, 0), time(7, 0))
    assert parse_quiet("11pm - 7am") == (time(23, 0), time(7, 0))
    assert parse_quiet("12 am to 8 am") == (time(0, 0), time(8, 0))
    assert parse_quiet("off") == "off"
    assert parse_quiet("none") == "off"
    assert parse_quiet("7am") is None
    assert parse_quiet("8am-8am") is None


def test_looks_like_token() -> None:
    assert looks_like_token("4242~SENTINELsentinelSENTINELsentinel00")
    assert not looks_like_token("hello there")
    assert not looks_like_token("short")
