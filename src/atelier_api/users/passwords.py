"""Hash and verify passwords using salted Argon2id hashes."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return an Argon2id hash with a fresh random salt for the password."""
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Check a password, returning false for mismatches or unrecognized hashes."""
    try:
        return _password_hash.verify(password, hashed_password)
    except UnknownHashError:
        return False
