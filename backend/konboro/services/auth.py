"""Authentication (12 §7, 00 §14.1).

Tokens carry the claims Cognito will give in S29: `sub`, `email`, `custom:tenant_id`, `custom:role`.
The API only sees the `TokenVerifier` interface, so S29 swaps `DevTokens` for a Cognito JWKS verifier
and nothing else changes. Until then, `DevTokens` both issues (dev login) and verifies.
"""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
from sqlalchemy import Engine, func, select

from konboro.db.ids import is_id
from konboro.db.models import User
from konboro.db.session import tenant_session
from konboro.settings import Settings

ISSUER = "konboro-dev"
AUDIENCE = "konboro"


class InvalidTokenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class Claims:
    subject: str
    email: str
    tenant_id: str
    role: str


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Claims: ...


def subject_of(user: User) -> str:
    """The token `sub`: the Cognito subject once there is one (S29), the user id until then."""
    return user.auth_subject or user.id


class DevTokens:
    """HS256 tokens signed with KONBORO_JWT_SECRET. Local and test only."""

    def __init__(self, secret: str, ttl: timedelta) -> None:
        self._secret = secret
        self._ttl = ttl

    def issue(self, user: User, now: datetime | None = None) -> str:
        issued = now or datetime.now(UTC)
        payload = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject_of(user),
            "email": user.email,
            "custom:tenant_id": user.tenant_id,
            "custom:role": user.role,
            "iat": issued,
            "exp": issued + self._ttl,
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def verify(self, token: str) -> Claims:
        try:
            data = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.PyJWTError as e:
            raise InvalidTokenError(str(e)) from e
        tenant_id = data.get("custom:tenant_id")
        if not isinstance(tenant_id, str) or not is_id(tenant_id, "tnt"):
            raise InvalidTokenError("token has no valid tenant")
        return Claims(
            subject=str(data["sub"]),
            email=str(data.get("email", "")),
            tenant_id=tenant_id,
            role=str(data.get("custom:role", "")),
        )


def dev_tokens(settings: Settings) -> DevTokens:
    return DevTokens(settings.jwt_secret.get_secret_value(), timedelta(minutes=settings.jwt_ttl_minutes))


def dev_login(settings: Settings, engine: Engine, email: str, password: str) -> User:
    """Check the shared dev password and find the user in the tenant the dev directory names.

    Every failure is the same error, so the response never tells which part was wrong.
    """
    expected = settings.dev_password.get_secret_value() if settings.dev_password else ""
    password_ok = bool(expected) and hmac.compare_digest(password.encode(), expected.encode())
    tenant_id = settings.dev_directory().get(email.strip().lower())
    if not password_ok or tenant_id is None or not is_id(tenant_id, "tnt"):
        raise InvalidCredentialsError
    with tenant_session(tenant_id, engine) as s:
        user = s.scalar(
            select(User).where(User.tenant_id == tenant_id, func.lower(User.email) == email.strip().lower())
        )
        if user is None:
            raise InvalidCredentialsError
        s.expunge(user)
    return user
