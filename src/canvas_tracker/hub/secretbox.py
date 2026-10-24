"""Encryption at rest for Canvas tokens (Fernet: AES-128-CBC + HMAC-SHA256).

The key lives outside the data volume (TOKEN_KEY / TOKEN_KEY_FILE), so a copy of
the databases alone doesn't reveal anyone's token.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")


class SecretBox:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.strip().encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            # Never echo the key; it would end up in logs.
            raise ValueError(
                "TOKEN_KEY isn't a valid key. Create one with: python -m canvas_tracker genkey"
            ) from None

    def seal(self, secret: str) -> bytes:
        return self._fernet.encrypt(secret.encode("utf-8"))

    def open(self, sealed: bytes) -> str:
        try:
            return self._fernet.decrypt(sealed).decode("utf-8")
        except InvalidToken:
            raise ValueError("stored token can't be decrypted with this TOKEN_KEY") from None
