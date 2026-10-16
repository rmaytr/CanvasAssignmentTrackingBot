"""Configuration from environment variables, validated at startup (PRD §7.8).

Secrets are accepted as ``X`` or ``X_FILE`` (a path, read and stripped). The
recommended form is the file, e.g. a Docker secret under /run/secrets.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable, Mapping
from datetime import time, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from canvas_tracker.domain.models import Settings

SECRET_FIELDS = ("canvas_token", "telegram_bot_token")


def validate_base_url(url: str) -> str:
    """HTTPS origin only: no credentials, path, query, fragment or raw IP address."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise ValueError("CANVAS_BASE_URL must start with https://")
    if parts.username is not None or parts.password is not None:
        raise ValueError("CANVAS_BASE_URL must not contain a username or password")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("CANVAS_BASE_URL must be just the site, e.g. https://canvas.school.edu")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("CANVAS_BASE_URL has no host name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("CANVAS_BASE_URL must use a host name, not an IP address")
    port = f":{parts.port}" if parts.port is not None else ""
    return f"https://{host}{port}"


def _parse_quiet(value: str) -> tuple[time, time] | None:
    if value.strip().lower() == "off":
        return None
    start, sep, end = value.partition("-")
    if not sep:
        raise ValueError('QUIET_HOURS must look like "00:00-08:00" or be "off"')
    return time.fromisoformat(start.strip()), time.fromisoformat(end.strip())


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    data_mode: Literal["api"] = "api"
    canvas_base_url: str
    canvas_token: SecretStr
    telegram_bot_token: SecretStr
    telegram_owner_id: int | None = None
    timezone: str
    digest_time: time = time(8, 0)
    digest_grace_until: time = time(12, 0)
    digest_lookahead_days: int = Field(14, ge=1, le=60)
    reminder_window_hours: int = Field(24, ge=1, le=168)
    reminder_interval_minutes: int = Field(120, ge=30)
    quiet_hours: str = "00:00-08:00"
    overdue_reminders: bool = False
    overdue_reminder_max_hours: int = Field(48, ge=1, le=336)
    hide_courses: str = ""
    db_path: Path = Path("/data/bot.db")
    item_retention_days: int = Field(30, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # load_config() reads the environment itself (to support *_FILE secrets).
        return (init_settings,)

    @field_validator("data_mode", mode="before")
    @classmethod
    def _mode(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "ical":
            raise ValueError("DATA_MODE=ical arrives in v1.0 (M2)")
        return value

    @field_validator("canvas_base_url")
    @classmethod
    def _base_url(cls, value: str) -> str:
        return validate_base_url(value)

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown TIMEZONE {value!r}; use an IANA name") from exc
        return value

    @field_validator("quiet_hours")
    @classmethod
    def _quiet(cls, value: str) -> str:
        _parse_quiet(value)
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


def _read_secret(env: Mapping[str, str], field: str) -> str:
    name = field.upper()
    direct, path = env.get(name), env.get(f"{name}_FILE")
    if direct is not None and path is not None:
        raise ValueError(f"set {name} or {name}_FILE, not both")
    if path is not None:
        text = Path(path).read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"{name}_FILE is empty")
        return text
    if direct is None or not direct.strip():
        raise ValueError(f"set {name} or {name}_FILE")
    return direct.strip()


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    source = os.environ if env is None else env
    values: dict[str, object] = {
        field: source[field.upper()]
        for field in AppConfig.model_fields
        if field not in SECRET_FIELDS and field.upper() in source
    }
    for field in SECRET_FIELDS:
        values[field] = _read_secret(source, field)
    return AppConfig(**values)  # type: ignore[arg-type]


def token_provider(cfg: AppConfig, env: Mapping[str, str] | None = None) -> Callable[[], str]:
    """The Canvas token. With CANVAS_TOKEN_FILE it is re-read on every call, so a renewed
    token takes effect without a restart (PRD §7.1)."""
    source = os.environ if env is None else env
    path = source.get("CANVAS_TOKEN_FILE")
    if path is None:
        token = cfg.canvas_token.get_secret_value()
        return lambda: token
    file = Path(path)
    return lambda: file.read_text(encoding="utf-8").strip()


def to_settings(cfg: AppConfig) -> Settings:
    quiet = _parse_quiet(cfg.quiet_hours)
    return Settings(
        tz=cfg.timezone,
        digest_time=cfg.digest_time,
        digest_grace_until=cfg.digest_grace_until,
        digest_lookahead=timedelta(days=cfg.digest_lookahead_days),
        reminder_window=timedelta(hours=cfg.reminder_window_hours),
        reminder_interval=timedelta(minutes=cfg.reminder_interval_minutes),
        quiet_start=None if quiet is None else quiet[0],
        quiet_end=None if quiet is None else quiet[1],
        overdue_reminders=cfg.overdue_reminders,
        overdue_reminder_max=timedelta(hours=cfg.overdue_reminder_max_hours),
        canvas_host=urlsplit(cfg.canvas_base_url).hostname or "",
    )


def hidden_courses(cfg: AppConfig) -> frozenset[str]:
    return frozenset(part.strip() for part in cfg.hide_courses.split(",") if part.strip())
