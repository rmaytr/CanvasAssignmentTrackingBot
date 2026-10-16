"""JSON-lines logging with secret redaction (PRD §10.2 item 5).

The Telegram token sits in the Bot API URL path, so any HTTP request log
would expose it: httpx/httpcore are kept at WARNING, and every record that
reaches the handler is scrubbed of known secrets and token-shaped strings.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime

REDACTED = "[REDACTED]"
_PATTERNS = (
    re.compile(r"bot\d{6,12}:[A-Za-z0-9_-]{30,}"),  # Bot API URL segment
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),  # Telegram bot token
    re.compile(r"\b\d{1,6}~[A-Za-z0-9]{20,}\b"),  # Canvas access token
)
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
}


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if len(s) >= 4}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str, secrets: Iterable[str]) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter(secrets))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
