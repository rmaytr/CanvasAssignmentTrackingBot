import io
import json
import logging
from collections.abc import Iterator

import pytest

from canvas_tracker.runtime.logging import JsonFormatter, RedactingFilter, configure_logging

TG_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789ab"
CANVAS_TOKEN = "4242~SecretCanvasTokenValue1234567890"


@pytest.fixture
def capture() -> Iterator[tuple[logging.Logger, io.StringIO]]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter(["my-exact-secret"]))
    logger = logging.getLogger("test.redaction")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    yield logger, stream
    logger.handlers = []


def test_telegram_token_in_url_is_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    logger.info("GET https://api.telegram.org/bot%s/getUpdates", TG_TOKEN)
    out = stream.getvalue()
    assert TG_TOKEN not in out and "[REDACTED]" in out


def test_exact_secret_in_args_is_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    logger.warning("token was %s", "my-exact-secret")
    assert "my-exact-secret" not in stream.getvalue()


def test_canvas_token_in_exception_is_redacted(capture: tuple[logging.Logger, io.StringIO]) -> None:
    logger, stream = capture
    try:
        raise RuntimeError(f"Authorization: Bearer {CANVAS_TOKEN}")
    except RuntimeError:
        logger.exception("sync failed")
    out = stream.getvalue()
    assert CANVAS_TOKEN not in out and "sync failed" in out


def test_output_is_json_lines_with_extra_fields(
    capture: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, stream = capture
    logger.info("tick", extra={"sends": 2})
    record = json.loads(stream.getvalue().splitlines()[0])
    assert record["msg"] == "tick" and record["level"] == "INFO" and record["sends"] == 2
    assert {"ts", "logger"} <= set(record)


def test_configure_logging_quiets_http_clients() -> None:
    configure_logging("DEBUG", secrets=["x" * 12])
    try:
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() == logging.WARNING
        assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    finally:
        logging.getLogger().handlers = []
