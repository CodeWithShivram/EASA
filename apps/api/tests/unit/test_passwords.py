import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.passwords import (
    DEFAULT_N,
    PasswordPolicyError,
    check_password_policy,
    hash_password,
    verify_password,
)

N = 2**10  # fast for tests; the format records the cost


def test_hash_and_verify_round_trip() -> None:
    stored = hash_password("a long synthetic password", n=N)

    assert stored.startswith(f"scrypt${N}$8$3$")
    assert verify_password("a long synthetic password", stored)
    assert not verify_password("a long synthetic passworD", stored)


def test_each_hash_has_its_own_salt() -> None:
    assert hash_password("same password here", n=N) != hash_password("same password here", n=N)


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "plaintext",
        "scrypt$1024$8$3$notbase64!$abc",
        "bcrypt$1024$8$3$c2FsdA==$aGFzaA==",
        f"scrypt${2**22}$8$3$c2FsdA==$aGFzaA==",  # a cost nobody configured
    ],
)
def test_malformed_or_absurd_stored_values_never_match(stored: str) -> None:
    assert verify_password("anything at all", stored) is False


def test_overlong_passwords_are_not_hashed() -> None:
    stored = hash_password("x" * 128, n=N)

    assert verify_password("x" * 128, stored)
    assert verify_password("x" * 129, stored) is False


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short", "12-128 characters"),
        ("x" * 129, "12-128 characters"),
        ("my-alice-password", "must not contain the username"),
    ],
)
def test_password_policy(password: str, message: str) -> None:
    with pytest.raises(PasswordPolicyError, match=message):
        check_password_policy(password, "alice")


def test_policy_accepts_a_good_password() -> None:
    check_password_policy("correct horse battery staple", "alice")


def test_production_needs_the_default_password_cost() -> None:
    with pytest.raises(ValidationError, match="at least"):
        Settings(_env_file=None, environment="production", password_hash_n=2**10)  # type: ignore[call-arg]
    assert Settings(_env_file=None, environment="production").password_hash_n == DEFAULT_N  # type: ignore[call-arg]


def test_password_cost_must_be_a_power_of_two() -> None:
    with pytest.raises(ValidationError, match="power of two"):
        Settings(_env_file=None, password_hash_n=3000)  # type: ignore[call-arg]
