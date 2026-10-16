"""Three simulated weeks across the 2026-11-01 US clock change (PRD §11.2 "Simulation")."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from canvas_tracker.store.repo import from_db
from tests.factories import make_settings
from tests.integration.sim_env import NY, ScenarioItem, build_env, ny

GOLDEN = Path(__file__).parent / "golden" / "simulation.txt"


def fixed(when: datetime) -> Callable[[datetime], datetime]:
    return lambda _t: when


def weekly_tuesdays() -> list[ScenarioItem]:
    return [
        ScenarioItem(100 + n, f"A weekly {n}", fixed(ny(m, d, 23, 59)))
        for n, (m, d) in enumerate([(10, 27), (11, 3), (11, 10)])
    ]


def scenario() -> list[ScenarioItem]:
    return [
        *weekly_tuesdays(),
        ScenarioItem(
            200, "B submitted", lambda _t: ny(10, 29, 23, 59), submitted_at=ny(10, 29, 15, 10)
        ),
        ScenarioItem(
            300,
            "C extended",
            lambda t: ny(11, 2, 17, 0) if t >= ny(10, 29, 9, 0) else ny(10, 30, 17, 0),
        ),
        ScenarioItem(
            400, "D last minute", lambda _t: ny(10, 28, 23, 30), posted_at=ny(10, 28, 22, 50)
        ),
        ScenarioItem(
            500,
            "E on paper",
            lambda _t: ny(10, 31, 12, 0),
            graded_at=ny(10, 26, 0, 0),
            submission_types=("on_paper",),
        ),
        ScenarioItem(600, "F overnight", lambda _t: ny(10, 31, 3, 0)),
        ScenarioItem(700, "G fall back", lambda _t: ny(11, 1, 23, 59)),
    ]


@pytest.mark.slow
async def test_three_week_simulation_matches_golden(tmp_path: Path, update_golden: bool) -> None:
    start = ny(10, 26, 0, 0)
    end = ny(11, 15, 0, 0)
    env = build_env(tmp_path, scenario(), make_settings(canvas_host="canvas.example.edu"), start)
    while env.clock.now < end:
        await env.runtime.tick()
        env.clock.now += timedelta(seconds=60)

    rows = env.store.conn.execute(
        "SELECT sent_at, kind, key FROM notifications WHERE status = 'sent' ORDER BY sent_at, key"
    ).fetchall()
    lines = []
    for r in rows:
        sent = from_db(r["sent_at"])
        assert sent is not None
        lines.append(f"{sent.astimezone(NY):%a %m-%d %H:%M} {r['kind']} {r['key']}")
    text = "\n".join(lines) + "\n"
    if update_golden:
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")

    # Spot checks that don't depend on the golden file
    hours = [int(line[10:12]) for line in lines]  # "Mon 10-26 08:00 kind key"
    assert not any(0 <= h < 8 for h in hours), "nothing is sent during quiet hours"
    assert len([line for line in lines if " digest " in line]) == 20  # one per day
    reminded = {
        ref
        for r in env.store.conn.execute(
            "SELECT item_refs FROM notifications WHERE kind IN ('reminder', 'new_urgent')"
        )
        for ref in json.loads(r["item_refs"])
    }
    assert "assignment-500" not in reminded, "graded on-paper work is done"
    assert "assignment-200" in reminded and "assignment-400" in reminded
