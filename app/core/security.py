"""Passwords and login tokens.

Two different jobs, two different tools:

  Password HASHING (pwdlib + Argon2): one-way. We can check a password against
  the hash, but nobody, including us, can turn the hash back into the password.

  Token SIGNING (PyJWT + HMAC-SHA256): a token's contents are only encoded,
  NOT encrypted. Anyone can read them (paste one into jwt.io). The signature
  only proves that we issued it and that nobody changed it. So a token must
  never contain anything secret.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings
from app.core.exceptions import Unauthorized

# Argon2, the algorithm FastAPI's security tutorial and OWASP's password-storage
# guidance both put first.
password_hash = PasswordHash.recommended()

# Used when a login names an email that doesn't exist. We still run one full
# hash check, so "no such user" takes as long as "wrong password" and an attacker
# can't discover which emails have accounts by timing the response.
_DUMMY_HASH = password_hash.hash("dummy-password-for-timing")


def hash_password(plain: str) -> str:
    return password_hash.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    if hashed is None:
        password_hash.verify(plain, _DUMMY_HASH)
        return False
    return password_hash.verify(plain, hashed)


def create_access_token(user_id: uuid.UUID, role: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),  # subject: who this token is about
        "role": role,  # informational only; permissions are checked against the database
        "type": "access",
        "iat": now,  # issued at
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),  # expires
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings | None = None) -> uuid.UUID:
    """Return the user id inside a valid token, or raise Unauthorized."""
    settings = settings or get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            # Pin the algorithm. Accepting whatever the token's header claims
            # (e.g. "none") is a classic JWT vulnerability.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Token has expired, please log in again") from None
    except jwt.PyJWTError:
        raise Unauthorized("Invalid token") from None
    if claims.get("type") != "access":
        raise Unauthorized("Invalid token")
    try:
        return uuid.UUID(claims["sub"])
    except ValueError:
        raise Unauthorized("Invalid token") from None
