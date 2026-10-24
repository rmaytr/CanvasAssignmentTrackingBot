"""A real Hub over temp files, with a fake Canvas and fake Telegram delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from canvas_tracker.bot.pairing import PairingCode
from canvas_tracker.hub.hub import Hub
from canvas_tracker.hub.registry import open_registry
from canvas_tracker.hub.secretbox import SecretBox, generate_key
from canvas_tracker.hub.signup import Signup
from canvas_tracker.notify.base import FakeNotifier
from canvas_tracker.sources.canvas_client import CanvasClient
from tests.factories import NOW

GOOD_TOKEN = "4242~GOODgoodGOODgoodGOODgood0000"
OTHER_TOKEN = "4243~OTHERotherOTHERotherOTHER000"
BAD_TOKEN = "4242~BADbadBADbadBADbadBADbad000"
NO_PLANNER_TOKEN = "4242~NOPLANnoplanNOPLANnoplan000"


class Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass
class FakeCanvas:
    """Answers profile and planner requests; remembers which token asked for what."""

    items: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # token -> planner
    time_zone: str | None = "America/Chicago"
    calls: list[tuple[str, str]] = field(default_factory=list)
    echo_401: bool = False  # answer everything with a 401 that echoes the token back

    def handler(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        self.calls.append((token, request.url.path))
        if self.echo_401:
            return httpx.Response(
                401, headers={"WWW-Authenticate": "Bearer"}, text=f"invalid token {token}"
            )
        if token == BAD_TOKEN:
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"}, json={})
        if request.url.path.endswith("/users/self/profile"):
            return httpx.Response(200, json={"name": "Private Name", "time_zone": self.time_zone})
        if request.url.path.endswith("/planner/items"):
            if token == NO_PLANNER_TOKEN:
                return httpx.Response(401, json={})  # no WWW-Authenticate: "not allowed"
            return httpx.Response(200, json=self.items.get(token, []))
        return httpx.Response(200, json=[])


@dataclass
class HubEnv:
    hub: Hub
    signup: Signup
    canvas: FakeCanvas
    clock: Clock
    notifiers: dict[int, FakeNotifier]
    data_dir: Path
    key: str


def build_hub(
    tmp_path: Path,
    *,
    owner: int | None = 1,
    max_users: int = 25,
    public: Callable[[str], bool] = lambda _host: True,
    pairing: PairingCode | None = None,
) -> HubEnv:
    canvas = FakeCanvas()
    clock = Clock()
    notifiers: dict[int, FakeNotifier] = {}
    key = generate_key()

    def client_factory(base: str, token: Callable[[], str]) -> CanvasClient:
        async def no_sleep(_s: float) -> None:
            return None

        return CanvasClient(
            base,
            token,
            transport=httpx.MockTransport(canvas.handler),
            sleep=no_sleep,
            max_retries=0,
        )

    async def host_check(host: str) -> bool:
        return public(host)

    def notifier(telegram_id: int) -> FakeNotifier:
        return notifiers.setdefault(telegram_id, FakeNotifier())

    hub = Hub(
        registry=open_registry(tmp_path / "registry.db"),
        box=SecretBox(key),
        data_dir=tmp_path,
        shared={},
        clock=clock,
        notifier_factory=notifier,
        client_factory=client_factory,
        host_check=host_check,
        max_users=max_users,
        owner_env_id=owner,
        pairing=pairing,
    )
    return HubEnv(hub, Signup(hub), canvas, clock, notifiers, tmp_path, key)


async def sign_up(
    env: HubEnv,
    telegram_id: int,
    *,
    token: str = GOOD_TOKEN,
    name: str = "Friend",
    url: str = "school.instructure.com",
) -> None:
    """Walk a user through every sign-up step (an invite for non-owners)."""
    arg = None if telegram_id == env.hub.owner_id() else env.hub.registry.create_invite(NOW)
    await env.signup.start(telegram_id, name, arg)
    for answer in (url, token):
        user = env.hub.registry.get_user(telegram_id)
        assert user is not None
        await env.signup.text(user, answer)
    for kind, value in (("tz", "America/Chicago"), ("dt", "07:00"), ("qh", "23:00-06:00")):
        user = env.hub.registry.get_user(telegram_id)
        assert user is not None
        await env.signup.choice(user, kind, value)
    user = env.hub.registry.get_user(telegram_id)
    assert user is not None and user.status == "active", user
