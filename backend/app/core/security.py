"""Password hashing and JWT issuance."""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext

from app.settings import settings

_pwd = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds
)


class PasswordPolicyError(ValueError):
    """Raised when a proposed password fails the published policy."""


#: Rejected outright regardless of length: these are the first guesses made
#: against any login form.
_COMMON_PASSWORDS = {
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyuiop", "letmein123", "adminadmin", "omicslab", "omicslab123",
    "changeme", "changeme123", "welcome123", "iloveyou1",
}


def validate_password(raw: str, *, email: str = "") -> None:
    """Enforce the password policy. Raises ``PasswordPolicyError`` on failure.

    Length carries most of the strength here; the character-class rule is kept
    deliberately mild so it does not push people towards 'Password1!'.
    """
    minimum = settings.min_password_length
    if len(raw) < minimum:
        raise PasswordPolicyError(
            f"Choose a password of at least {minimum} characters."
        )
    if len(raw) > 200:
        raise PasswordPolicyError("That password is too long (200 characters maximum).")
    if raw.lower() in _COMMON_PASSWORDS:
        raise PasswordPolicyError(
            "That password is one of the most commonly guessed ones. Choose another."
        )
    if email and raw.lower() == email.lower():
        raise PasswordPolicyError("Your password cannot be your email address.")
    if raw.isdigit() or raw.isalpha():
        raise PasswordPolicyError(
            "Mix letters with at least one number or symbol."
        )


def hash_password(raw: str) -> str:
    #: bcrypt silently truncates beyond 72 bytes, so refuse rather than hash a
    #: prefix and let a longer password authenticate on its first 72 bytes.
    if len(raw.encode("utf-8")) > 72:
        raise PasswordPolicyError(
            "That password is too long to hash safely (72 bytes maximum)."
        )
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    if len(raw.encode("utf-8")) > 72:
        return False
    try:
        return _pwd.verify(raw, hashed)
    except ValueError:
        #: A malformed or truncated stored hash is a failed login, not a 500.
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None
