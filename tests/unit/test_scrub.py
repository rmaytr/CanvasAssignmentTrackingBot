from pathlib import Path

import pytest

from spike.scrub import scrub

RAW = {
    "html_url": (
        "https://canvas.school.edu/courses/12/assignments/34"
        "?access_token=1234~AbCdEfGhIjKlMnOpQrStUvWxYz"
    ),
    "title": "Essay about Jane Doe",
    "context_name": "BIO 201 - Section 4",
    "description": "<p>secret instructions</p>",
    "user": {"name": "Jane Doe", "email": "jane@school.edu", "id": 987654},
    "nested": [{"note": "token 5678~ZyXwVuTsRqPoNmLkJiHgFeDcBa here"}],
}


def test_scrub_removes_tokens_emails_names_host_and_descriptions() -> None:
    out = repr(scrub(RAW, canvas_host="canvas.school.edu"))
    for needle in [
        "1234~",
        "5678~",
        "jane@school.edu",
        "Jane Doe",
        "canvas.school.edu",
        "secret instructions",
        "987654",
    ]:
        assert needle not in out
    assert "canvas.example.edu" in out


def test_scrub_is_deterministic_and_keeps_structure() -> None:
    a = scrub(RAW, "canvas.school.edu")
    b = scrub(RAW, "canvas.school.edu")
    assert a == b
    assert set(a) == set(RAW) - {"description"}


PROFILE = {
    "id": 987654,
    "name": "Jane Doe",
    "short_name": "Jane",
    "sortable_name": "Doe, Jane",
    "primary_email": "jane@school.edu",
    "login_id": "jdoe42",
    "sis_user_id": "S1234567",
    "integration_id": "INT-77",
    "lti_user_id": "lti-abc-123",
    "uuid": "uuid-xyz-789",
    "calendar": {"ics": "https://canvas.school.edu/feeds/calendars/user_FEEDSECRET123.ics"},
}


def test_scrub_removes_profile_identifiers_and_feed_url() -> None:  # review I7
    out = repr(scrub(PROFILE, canvas_host="canvas.school.edu"))
    for needle in [
        "987654",
        "jdoe42",
        "S1234567",
        "INT-77",
        "lti-abc-123",
        "uuid-xyz-789",
        "FEEDSECRET123",
        "jane@school.edu",
        "Jane",
    ]:
        assert needle not in out


def test_cli_only_writes_fixture_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import sys

    from spike.scrub import main

    src, dest = tmp_path / "out", tmp_path / "fixtures"
    src.mkdir()
    for name in [
        "planner_items.json",
        "planner_items.meta.json",
        "assignment_groups_12.json",
        "users_self_profile.json",
        "courses.json",
    ]:
        (src / name).write_text(json.dumps([{"title": "x"}]))
    monkeypatch.setattr(
        sys, "argv", ["scrub.py", "--host", "canvas.school.edu", str(src), str(dest)]
    )
    main()
    assert sorted(p.name for p in dest.iterdir()) == [
        "assignment_groups_12.json",
        "planner_items.json",
    ]
