"""M0 spike: record how the owner's Canvas answers the bot's questions (S3-S7).

Owner-only. GET requests only. The token is read from a file, never from the
command line (arguments show up in `ps` and shell history). Raw responses go
to spike/out/ (git-ignored); run spike/scrub.py before committing anything.

Usage: uv run python spike/probe_canvas.py --base-url https://canvas.school.edu \
           --token-file ~/canvas_token.txt
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

USER_AGENT = (
    "CanvasAssignmentTrackingBot/0.1.0-spike "
    "(+https://github.com/rmaytr/CanvasAssignmentTrackingBot)"
)
OUT = Path(__file__).parent / "out"


def _save(name: str, resp: httpx.Response) -> Any:
    OUT.mkdir(exist_ok=True)
    meta = {
        "status": resp.status_code,
        "etag": resp.headers.get("etag"),
        "link": resp.headers.get("link"),
    }
    (OUT / f"{name}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if resp.status_code == 200:
        data = resp.json()
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--token-file", required=True, type=Path)
    args = ap.parse_args()
    token = args.token_file.expanduser().read_text(encoding="utf-8").strip()
    now = datetime.now(UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    with httpx.Client(
        base_url=args.base_url, headers=headers, timeout=20, follow_redirects=False
    ) as c:

        def get(name: str, path: str, **params: Any) -> tuple[httpx.Response, Any]:
            r = c.get(path, params=params)
            print(f"{name:<24} HTTP {r.status_code}")
            return r, _save(name, r)

        _, me = get("users_self", "/api/v1/users/self")
        _, profile = get("users_self_profile", "/api/v1/users/self/profile")
        planner_params = {
            "start_date": (now - timedelta(days=28)).strftime(fmt),
            "end_date": (now + timedelta(days=21)).strftime(fmt),
            "per_page": "100",
        }
        r, planner = get("planner_items", "/api/v1/planner/items", **planner_params)
        etag = r.headers.get("etag")
        if etag:
            r2 = c.get(
                "/api/v1/planner/items", params=planner_params, headers={"If-None-Match": etag}
            )
            print(
                f"{'planner_items (etag)':<24} HTTP {r2.status_code}"
                "  <- 304 means ETag polling works (S7)"
            )
            _save("planner_items_etag_retry", r2)
        _, courses = get("courses", "/api/v1/courses", enrollment_state="active", per_page="100")
        for course in courses or []:
            cid = course.get("id")
            get(
                f"assignment_groups_{cid}",
                f"/api/v1/courses/{cid}/assignment_groups",
                **{"include[]": "assignments", "per_page": "100"},
            )
        get("users_self_tokens", "/api/v1/users/self/tokens")

    print("\nWhat this answers:")
    print(
        "  S3 token expiry via API: see out/users_self_tokens.meta.json (status)"
        " and look for 'expires_at'"
    )
    tz = (profile or {}).get("time_zone") or (me or {}).get("time_zone")
    print(f"  S4 profile time zone: {tz!r}")
    print("  S5 assignment group JSON: out/assignment_groups_*.json (look for 'group_weight')")
    overrides = sum(1 for i in planner or [] if i.get("planner_override"))
    print(f"  S6 planner items with an override: {overrides} of {len(planner or [])}")
    print("  S7 ETag: see the '(etag)' line above")


if __name__ == "__main__":
    main()
