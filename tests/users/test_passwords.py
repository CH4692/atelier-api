import pytest

from atelier_api.users.passwords import hash_password, verify_password


def test_argon2_hash_can_verify_correct_password():
    password = "test-password-123"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert password not in encoded
    assert verify_password(password, encoded) is True
    assert verify_password("different-password", encoded) is False


def test_same_password_uses_different_random_salts():
    password = "test-password-123"
    first = hash_password(password)
    second = hash_password(password)
    assert first != second
    assert verify_password(password, first)
    assert verify_password(password, second)


@pytest.mark.parametrize("encoded", ["", "not-a-hash", "$argon2id$invalid"])
def test_unknown_or_malformed_hash_does_not_verify(encoded):
    assert verify_password("test-password-123", encoded) is False


def test_long_unicode_password_is_not_truncated():
    password = "ä" * 100 + "first-suffix"
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password("ä" * 100 + "other-suffix", encoded)


def test_hashes_with_older_cost_parameters_remain_verifiable():
    from argon2 import PasswordHasher

    encoded = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(
        "test-password-123"
    )
    assert verify_password("test-password-123", encoded)
    assert not verify_password("wrong-password", encoded)
