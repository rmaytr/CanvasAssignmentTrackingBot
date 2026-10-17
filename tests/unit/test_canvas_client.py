import asyncio
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from canvas_tracker.sources.canvas_client import (
    USER_AGENT,
    CanvasAuthError,
    CanvasClient,
    CanvasProtocolError,
    CanvasUnavailable,
)

BASE = "https://canvas.example.edu"


def make_client(sleep: AsyncMock | None = None, token: Any = None) -> CanvasClient:
    return CanvasClient(
        BASE,
        token or (lambda: "tok"),
        sleep=sleep or AsyncMock(),
        rand=lambda: 0.5,
    )


@respx.mock
async def test_get_all_follows_link_pages_in_order() -> None:
    route = respx.get(f"{BASE}/api/v1/things")
    route.side_effect = [
        httpx.Response(
            200, json=[1, 2], headers={"Link": f'<{BASE}/api/v1/things?page=2>; rel="next"'}
        ),
        httpx.Response(
            200, json=[3], headers={"Link": f'<{BASE}/api/v1/things?page=3>; rel="next"'}
        ),
        httpx.Response(200, json=[4]),
    ]
    assert await make_client().get_all("/api/v1/things") == [1, 2, 3, 4]


@respx.mock
async def test_cross_host_pagination_is_refused() -> None:
    respx.get(f"{BASE}/api/v1/things").respond(
        200, json=[1], headers={"Link": '<https://evil.example/api/v1/things?page=2>; rel="next"'}
    )
    with pytest.raises(CanvasProtocolError, match="cross-host pagination refused"):
        await make_client().get_all("/api/v1/things")


@respx.mock
async def test_redirects_are_refused() -> None:
    respx.get(f"{BASE}/api/v1/x").respond(302, headers={"Location": "https://evil.example/"})
    with pytest.raises(CanvasProtocolError, match="redirect refused"):
        await make_client().get_json("/api/v1/x")


@respx.mock
async def test_etag_304_means_not_modified() -> None:
    route = respx.get(f"{BASE}/api/v1/planner/items")
    route.respond(304)
    result = await make_client().get_all_if_changed("/api/v1/planner/items", {}, etag='W/"abc"')
    assert result.not_modified and result.data == []
    assert route.calls.last.request.headers["If-None-Match"] == 'W/"abc"'


@respx.mock
async def test_etag_200_returns_data_and_new_etag() -> None:
    respx.get(f"{BASE}/api/v1/planner/items").respond(200, json=[1], headers={"ETag": 'W/"new"'})
    result = await make_client().get_all_if_changed("/api/v1/planner/items", {}, etag=None)
    assert (result.not_modified, result.data, result.etag) == (False, [1], 'W/"new"')


@respx.mock
async def test_throttling_retries_with_full_jitter() -> None:
    sleep = AsyncMock()
    respx.get(f"{BASE}/api/v1/x").side_effect = [
        httpx.Response(429),
        httpx.Response(429),
        httpx.Response(200, json={"ok": True}),
    ]
    assert await make_client(sleep).get_json("/api/v1/x") == {"ok": True}
    assert [c.args[0] for c in sleep.await_args_list] == [1.0, 2.0]


@respx.mock
async def test_403_rate_limit_body_is_throttling_but_plain_403_is_not() -> None:
    respx.get(f"{BASE}/api/v1/x").side_effect = [
        httpx.Response(403, text="403 Forbidden (Rate Limit Exceeded)"),
        httpx.Response(200, json=[]),
    ]
    assert await make_client().get_json("/api/v1/x") == []
    respx.get(f"{BASE}/api/v1/y").respond(403, text="user not authorized")
    with pytest.raises(CanvasProtocolError):
        await make_client().get_json("/api/v1/y")


@respx.mock
async def test_persistent_5xx_gives_unavailable() -> None:
    route = respx.get(f"{BASE}/api/v1/x").respond(503)
    with pytest.raises(CanvasUnavailable):
        await make_client().get_json("/api/v1/x")
    assert route.call_count == 5


@respx.mock
async def test_transport_errors_are_retried() -> None:
    respx.get(f"{BASE}/api/v1/x").side_effect = [
        httpx.ConnectTimeout("t"),
        httpx.Response(200, json=1),
    ]
    assert await make_client().get_json("/api/v1/x") == 1


@respx.mock
async def test_401_is_auth_error_after_one_request() -> None:
    route = respx.get(f"{BASE}/api/v1/x").respond(
        401, headers={"WWW-Authenticate": 'Bearer realm="canvas-lms"'}
    )
    with pytest.raises(CanvasAuthError):
        await make_client().get_json("/api/v1/x")
    assert route.call_count == 1


@respx.mock
async def test_headers_user_agent_and_fresh_token_each_request() -> None:
    tokens = iter(["first", "second"])
    route = respx.get(f"{BASE}/api/v1/x").respond(200, json={})
    client = make_client(token=lambda: next(tokens))
    await client.get_json("/api/v1/x")
    await client.get_json("/api/v1/x")
    sent = [c.request.headers for c in route.calls]
    assert [h["Authorization"] for h in sent] == ["Bearer first", "Bearer second"]
    assert all(h["User-Agent"] == USER_AGENT for h in sent)
    assert USER_AGENT.startswith("CanvasAssignmentTrackingBot/0.1.0 (+https://github.com/")


async def test_only_api_v1_paths_are_allowed() -> None:
    with pytest.raises(ValueError):
        await make_client().get_json("/login")
    with pytest.raises(ValueError):
        await make_client().get_json("https://evil.example/api/v1/x")


def test_client_exposes_no_write_methods() -> None:
    public = {n for n in dir(CanvasClient) if not n.startswith("_")}
    assert public == {"get_json", "get_all", "get_all_if_changed", "aclose"}


@respx.mock
async def test_requests_never_overlap() -> None:
    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=[])

    respx.get(f"{BASE}/api/v1/x").mock(side_effect=handler)
    client = make_client()
    await asyncio.gather(client.get_json("/api/v1/x"), client.get_json("/api/v1/x"))
    assert peak == 1


@respx.mock
async def test_non_json_200_is_a_protocol_error() -> None:  # review I1
    respx.get(f"{BASE}/api/v1/x").respond(200, text="<html>Wi-Fi login</html>")
    with pytest.raises(CanvasProtocolError):
        await make_client().get_json("/api/v1/x")
    with pytest.raises(CanvasProtocolError):
        await make_client().get_all("/api/v1/x")


async def test_unreadable_token_file_is_an_auth_error() -> None:
    def broken() -> str:
        raise FileNotFoundError("/run/secrets/canvas_token")

    with pytest.raises(CanvasAuthError):
        await make_client(token=broken).get_json("/api/v1/x")


@respx.mock
async def test_401_records_whether_canvas_challenged_the_token() -> None:  # review I2
    respx.get(f"{BASE}/api/v1/a").respond(
        401, headers={"WWW-Authenticate": 'Bearer realm="canvas-lms"'}
    )
    respx.get(f"{BASE}/api/v1/b").respond(401, json={"status": "unauthorized"})
    with pytest.raises(CanvasAuthError) as challenged:
        await make_client().get_json("/api/v1/a")
    with pytest.raises(CanvasAuthError) as plain:
        await make_client().get_json("/api/v1/b")
    assert challenged.value.challenged is True and plain.value.challenged is False
