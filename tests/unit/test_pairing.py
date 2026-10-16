import random
from datetime import datetime, timedelta

from canvas_tracker.bot.pairing import ALPHABET, PairingCode, PairingResult
from tests.factories import NOW


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def make() -> tuple[PairingCode, Clock, list[str]]:
    clock = Clock()
    issued: list[str] = []
    return PairingCode(clock, issued.append, rng=random.Random(1)), clock, issued  # noqa: S311 - deterministic test RNG


def test_code_shape() -> None:
    code, _, issued = make()
    assert len(code.code) == 8 and set(code.code) <= set(ALPHABET)
    assert code.expires_at == NOW + timedelta(minutes=15)
    assert issued == []


def test_correct_code_case_insensitive() -> None:
    code, _, _ = make()
    assert code.check(code.code.lower()) is PairingResult.OK


def test_four_wrong_then_right_is_ok() -> None:
    code, _, _ = make()
    for _ in range(4):
        assert code.check("WRONG000") is PairingResult.WRONG
    assert code.check(code.code) is PairingResult.OK


def test_fifth_wrong_locks_and_issues_new_code() -> None:
    code, _, issued = make()
    old = code.code
    results = [code.check("WRONG000") for _ in range(5)]
    assert results[-1] is PairingResult.LOCKED and results[:4] == [PairingResult.WRONG] * 4
    assert issued == [code.code] and code.code != old
    assert code.check(old) is PairingResult.WRONG


def test_expired_code_issues_new_one() -> None:
    code, clock, issued = make()
    old = code.code
    clock.now = NOW + timedelta(minutes=15)
    assert code.check(old) is PairingResult.EXPIRED
    assert len(issued) == 1 and code.code != old


def test_non_ascii_attempt_is_just_wrong() -> None:
    code, _, _ = make()
    assert code.check("ÄÖÜ✅") is PairingResult.WRONG
