"""Bot-wide configuration from environment variables, validated at startup.

Friends mode: each user's Canvas address, token, time zone, morning time and
quiet hours are set in the chat and kept in the registry, not here. Secrets
are accepted as ``X`` or ``X_FILE`` (a path, read and stripped); the file form
is meant for Docker secrets under /run/secrets.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

if TYPE_CHECKING:
    from canvas_tracker.notify.email import SmtpConfig

SECRET_FIELDS = ("telegram_bot_token", "token_key")
OPTIONAL_SECRET_FIELDS = ("smtp_password",)


def validate_base_url(url: str) -> str:
    """HTTPS origin only: no credentials, path, query, fragment or raw IP address."""
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise ValueError("the Canvas address must start with https://")
    if parts.username is not None or parts.password is not None:
        raise ValueError("the Canvas address must not contain a username or password")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("the Canvas address must be just the site, e.g. https://canvas.school.edu")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("the Canvas address has no host name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("the Canvas address must use a host name, not an IP address")
    port = f":{parts.port}" if parts.port is not None else ""
    return f"https://{host}{port}"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    telegram_bot_token: SecretStr
    token_key: SecretStr
    owner_telegram_id: int | None = None
    data_dir: Path = Path("/data")
    max_users: int = Field(25, ge=1, le=500)
    digest_lookahead_days: int = Field(14, ge=1, le=60)
    reminder_window_hours: int = Field(24, ge=1, le=168)
    reminder_interval_minutes: int = Field(120, ge=30)
    overdue_reminders: bool = False
    overdue_reminder_max_hours: int = Field(48, ge=1, le=336)
    item_retention_days: int = Field(30, ge=1)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Email (optional): unset SMTP_HOST means the bot never sends email.
    smtp_host: str | None = None
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_security: Literal["starttls", "tls"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    email_from: str | None = None
    email_from_name: str = Field("Canvas Tracker", min_length=1, max_length=64)

    @field_validator("smtp_host", "smtp_username", "email_from", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("smtp_security", mode="before")
    @classmethod
    def _security(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("email_from")
    @classmethod
    def _from(cls, value: str | None) -> str | None:
        from canvas_tracker.notify.email import normalize_address

        if value is None:
            return None
        address = normalize_address(value)
        if address is None:
            raise ValueError("must be a plain email address, e.g. bot@example.com")
        return address

    @model_validator(mode="after")
    def _email_complete(self) -> AppConfig:
        if self.smtp_host is not None:
            if self.email_from is None:
                raise ValueError("EMAIL_FROM is required when SMTP_HOST is set")
            if (self.smtp_username is None) != (self.smtp_password is None):
                raise ValueError("set both SMTP_USERNAME and SMTP_PASSWORD, or neither")
        return self

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

    @field_validator("owner_telegram_id", mode="before")
    @classmethod
    def _owner(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None  # "OWNER_TELEGRAM_ID=" means "not set": use pairing
        return value

    @field_validator("token_key")
    @classmethod
    def _key(cls, value: SecretStr) -> SecretStr:
        from canvas_tracker.hub.secretbox import SecretBox

        SecretBox(value.get_secret_value())  # raises a message that never echoes the key
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
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except PermissionError:
            raise ValueError(
                f"{name}_FILE can't be read (permission denied). The container runs as "
                f"user 10001, so on Linux give it the file: sudo chown 10001:10001 {path}"
            ) from None
        if not text:
            raise ValueError(f"{name}_FILE is empty")
        return text
    if direct is None or not direct.strip():
        raise ValueError(f"set {name} or {name}_FILE")
    return direct.strip()


def _read_optional_secret(env: Mapping[str, str], field: str) -> str | None:
    """Like ``_read_secret``, but unset, blank or an empty file all mean "not set"
    (compose always mounts secrets/smtp_password.txt, which is empty without email)."""
    name = field.upper()
    path = env.get(f"{name}_FILE")
    if path is not None and env.get(name, "").strip():
        raise ValueError(f"set {name} or {name}_FILE, not both")
    if path is not None:
        try:
            if not Path(path).read_text(encoding="utf-8").strip():
                return None
        except FileNotFoundError:
            return None
        except PermissionError:
            pass  # _read_secret explains how to fix it
    elif not env.get(name, "").strip():
        return None
    without_blank = {k: v for k, v in env.items() if k != name or v.strip()}
    return _read_secret(without_blank, field)


def load_config(env: Mapping[str, str] | None = None) -> AppConfig:
    source = os.environ if env is None else env
    values: dict[str, object] = {
        field: source[field.upper()]
        for field in AppConfig.model_fields
        if field not in (*SECRET_FIELDS, *OPTIONAL_SECRET_FIELDS) and field.upper() in source
    }
    for field in SECRET_FIELDS:
        # Wrapped before validation, so no error message can ever echo a secret.
        values[field] = SecretStr(_read_secret(source, field))
    for field in OPTIONAL_SECRET_FIELDS:
        optional = _read_optional_secret(source, field)
        if optional is not None:
            values[field] = SecretStr(optional)
    try:
        return AppConfig(**values)  # type: ignore[arg-type]
    except ValidationError as exc:
        problems = [
            f"{'.'.join(str(part) for part in error['loc']).upper() or 'CONFIG'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        ]
        raise ValueError("; ".join(problems)) from None


def base_settings(cfg: AppConfig) -> dict[str, object]:
    """The reminder rules every user shares; each user adds their own zone and times."""
    return {
        "digest_lookahead": timedelta(days=cfg.digest_lookahead_days),
        "reminder_window": timedelta(hours=cfg.reminder_window_hours),
        "reminder_interval": timedelta(minutes=cfg.reminder_interval_minutes),
        "overdue_reminders": cfg.overdue_reminders,
        "overdue_reminder_max": timedelta(hours=cfg.overdue_reminder_max_hours),
    }


def smtp_config(cfg: AppConfig) -> SmtpConfig | None:
    """The mail server settings, or None when email isn't configured."""
    from canvas_tracker.notify.email import SmtpConfig

    if cfg.smtp_host is None or cfg.email_from is None:
        return None
    return SmtpConfig(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        security=cfg.smtp_security,
        username=cfg.smtp_username,
        password=cfg.smtp_password.get_secret_value() if cfg.smtp_password else None,
        sender=cfg.email_from,
        sender_name=cfg.email_from_name,
    )
