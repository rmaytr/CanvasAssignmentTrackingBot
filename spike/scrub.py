"""Scrub raw Canvas API responses into fixtures that are safe to commit.

Owner-only spike tool. Removes tokens, emails, names, titles, the school's
Canvas host, free-text bodies and user IDs, replacing them with stable
placeholders so the JSON keeps its structure.

Usage: uv run python spike/scrub.py --host canvas.school.edu spike/out tests/fixtures/canvas
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"\d{1,6}~[A-Za-z0-9]{20,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DROP_KEYS = frozenset(
    {
        "description",
        "message",
        "body",
        "sis_user_id",
        "sis_import_id",
        "integration_id",
        "login_id",
        "lti_user_id",
        "uuid",
        "token_hint",
        "primary_email",
        "avatar_url",
        "bio",
        "pronouns",
    }
)
# A dict with any of these keys describes a person, so its "id" is personal too.
USER_MARKERS = frozenset(
    {"login_id", "sortable_name", "primary_email", "sis_user_id", "short_name"}
)
FEED_RE = re.compile(r"https?://[^\s\"']*/feeds/[^\s\"']*")
FIXTURE_PATTERNS = ("planner_items*.json", "assignment_groups_*.json")
PLACEHOLDER_KEYS = {
    "title": "Title",
    "name": "Name",
    "display_name": "Name",
    "short_name": "Name",
    "sortable_name": "Name",
    "context_name": "Course",
    "course_code": "Course",
}
USER_ID_KEYS = frozenset({"id", "user_id"})
FAKE_HOST = "canvas.example.edu"


class _Scrubber:
    def __init__(self, canvas_host: str) -> None:
        self._host_re = re.compile(re.escape(canvas_host), re.IGNORECASE)
        self._placeholders: dict[tuple[str, str], str] = {}
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._ids: dict[int, int] = {}

    def _placeholder(self, prefix: str, value: str) -> str:
        key = (prefix, value)
        if key not in self._placeholders:
            self._counters[prefix] += 1
            self._placeholders[key] = f"{prefix} {self._counters[prefix]}"
        return self._placeholders[key]

    def _fake_id(self, value: int) -> int:
        if value not in self._ids:
            self._ids[value] = 1000 + len(self._ids)
        return self._ids[value]

    def _text(self, value: str) -> str:
        value = FEED_RE.sub(f"https://{FAKE_HOST}/feeds/REDACTED", value)  # feed URLs are secrets
        value = TOKEN_RE.sub("REDACTED_TOKEN", value)
        value = EMAIL_RE.sub("user@example.edu", value)
        return self._host_re.sub(FAKE_HOST, value)

    def walk(self, obj: Any, in_user: bool = False) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            in_user = in_user or bool(USER_MARKERS & obj.keys())
            for key, value in obj.items():
                if key in DROP_KEYS:
                    continue
                if key in PLACEHOLDER_KEYS and isinstance(value, str):
                    out[key] = self._placeholder(PLACEHOLDER_KEYS[key], value)
                elif ((in_user and key in USER_ID_KEYS) or key == "user_id") and isinstance(
                    value, int
                ):
                    out[key] = self._fake_id(value)
                else:
                    out[key] = self.walk(value, in_user=in_user or key == "user")
            return out
        if isinstance(obj, list):
            return [self.walk(item, in_user=in_user) for item in obj]
        if isinstance(obj, str):
            return self._text(obj)
        return obj


def scrub(obj: Any, canvas_host: str) -> Any:
    """Return a scrubbed deep copy of ``obj``; the same input always gives the same output."""
    return _Scrubber(canvas_host).walk(obj)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="your school's Canvas host")
    parser.add_argument("in_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    scrubber = _Scrubber(args.host)  # one scrubber so placeholders match across files
    sources = sorted(
        {p for pattern in FIXTURE_PATTERNS for p in args.in_dir.glob(pattern)}
        - set(args.in_dir.glob("*.meta.json"))
    )  # only the responses tests need; profiles etc. stay in spike/out
    for src in sources:
        data = json.loads(src.read_text(encoding="utf-8"))
        dest = args.out_dir / src.name
        dest.write_text(json.dumps(scrubber.walk(data), indent=2) + "\n", encoding="utf-8")
        print(f"scrubbed {src.name} -> {dest}")


if __name__ == "__main__":
    main()
