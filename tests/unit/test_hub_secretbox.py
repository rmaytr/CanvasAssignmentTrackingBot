import pytest

from canvas_tracker.hub.secretbox import SecretBox, generate_key

TOKEN = "4242~SENTINELsentinelSENTINELsentinel00"


def test_round_trip_and_ciphertext_hides_the_token() -> None:
    box = SecretBox(generate_key())
    sealed = box.seal(TOKEN)
    assert TOKEN.encode() not in sealed
    assert box.open(sealed) == TOKEN


def test_wrong_key_cannot_open() -> None:
    sealed = SecretBox(generate_key()).seal(TOKEN)
    with pytest.raises(ValueError, match="TOKEN_KEY"):
        SecretBox(generate_key()).open(sealed)


def test_bad_key_is_a_readable_error_without_the_key() -> None:
    with pytest.raises(ValueError, match="TOKEN_KEY") as info:
        SecretBox("not-a-real-key")
    assert "not-a-real-key" not in str(info.value)
