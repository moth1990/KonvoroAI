"""Who is calling, in which tenant, and may they (00 §14.1, docs/db-schema.md §2).

Every route except the public ones in `PUBLIC_ROUTES` depends on `current_actor`, through `require(permission)`.
`current_actor`:
1. reads and verifies the bearer token;
2. opens a `tenant_session` for the token's tenant, which commits when the route function returns,
   before the response is sent;
3. loads the user in that tenant. The DB's role is the one that counts, not the token's.

`tests/integration/test_api_routes.py` enumerates the app's routes to prove it.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from konboro.db.models import Tenant, User
from konboro.db.session import tenant_session
from konboro.domain.flags import is_enabled
from konboro.domain.permissions import Permission, allowed
from konboro.services import flags
from konboro.services.auth import InvalidTokenError, TokenVerifier

from .errors import ApiError

# Reachable without a token. Anything else without `current_actor` fails the route audit.
PUBLIC_ROUTES = frozenset({("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/password-reset")})

_bearer = HTTPBearer(auto_error=False, description="A token from POST /auth/login (Cognito from S29)")


@dataclass
class Actor:
    user_id: str
    tenant_id: str
    email: str
    role: str
    session: Session
    _flags: dict[str, bool] | None = field(default=None, repr=False)

    @property
    def flags(self) -> dict[str, bool]:
        if self._flags is None:
            self._flags = flags.tenant_flags(self.session, self.tenant_id)
        return self._flags


def current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Iterator[Actor]:
    if credentials is None:
        raise ApiError(401, "unauthorized")
    verifier: TokenVerifier = request.app.state.verifier
    try:
        claims = verifier.verify(credentials.credentials)
    except InvalidTokenError as e:
        raise ApiError(401, "unauthorized") from e

    with tenant_session(claims.tenant_id, request.app.state.engine) as session:
        row = session.execute(
            select(User, Tenant.status)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.tenant_id == claims.tenant_id,
                or_(
                    User.auth_subject == claims.subject,
                    and_(User.auth_subject.is_(None), User.id == claims.subject),
                ),
            )
        ).first()
        if row is None:
            raise ApiError(401, "unauthorized")
        user, status = row
        if status != "active":
            raise ApiError(403, "tenant_suspended")
        yield Actor(user_id=user.id, tenant_id=user.tenant_id, email=user.email, role=user.role, session=session)


# scope="function": the tenant transaction ends with the route function, so a failed commit is an error
# response, never a success the client saw before the write was lost.
ActorDep = Annotated[Actor, Depends(current_actor, scope="function")]


def require(permission: Permission) -> Callable[[Actor], Actor]:
    def check(actor: ActorDep) -> Actor:
        if not allowed(actor.role, permission):
            raise ApiError(403, "forbidden")
        return actor

    check.__name__ = f"require_{permission.name.lower()}"
    return check


def require_flag(key: str) -> Callable[[Actor], None]:
    """A flag that is off makes the route behave as if it does not exist: 404 (13 §3.1–3.2)."""

    def check(actor: ActorDep) -> None:
        if not is_enabled(actor.flags, key):
            raise ApiError(404, "not_found")

    check.__name__ = f"require_flag_{key}"
    return check
