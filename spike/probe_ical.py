"""M0 spike: inspect the Canvas calendar feed (S1). Owner-only.

The feed URL is a secret; read it from a file. Prints only counts and shapes.
Usage: uv run python spike/probe_ical.py --feed-file ~/canvas_feed_url.txt
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import httpx


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed-file", required=True, type=Path)
    args = ap.parse_args()
    url = args.feed_file.expanduser().read_text(encoding="utf-8").strip()
    resp = httpx.get(url, timeout=30, follow_redirects=False)
    print(f"HTTP {resp.status_code}, {len(resp.content)} bytes")
    uid_kinds: Counter[str] = Counter()
    dtstart_kinds: Counter[str] = Counter()
    for line in resp.text.splitlines():
        if line.startswith("UID:"):
            uid = line[4:]
            uid_kinds["-".join(uid.split("-")[:2])] += 1
        elif line.startswith("DTSTART"):
            dtstart_kinds["DATE (all-day)" if "VALUE=DATE:" in line else "DATE-TIME"] += 1
    print("UID prefixes:", dict(uid_kinds))
    print("DTSTART kinds:", dict(dtstart_kinds))
    print(
        "S1: submit one assignment, run this again later, and compare the event-assignment count."
    )


if __name__ == "__main__":
    main()
