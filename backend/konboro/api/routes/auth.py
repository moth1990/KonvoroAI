"""Dev login, logout and the password-reset stub (S03; Cognito replaces the login in S29)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from konboro.domain.permissions import Permission
from konboro.services import auth
from konboro.settings import Settings

from ..deps import Actor, require
from ..errors import ERROR_RESPONSES, ApiError
from ..schemas import LoginIn, PasswordResetIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERROR_RESPONSES)


@router.post("/login")
def login(body: LoginIn, request: Request) -> TokenOut:
    settings: Settings = request.app.state.settings
    if not settings.dev_login_enabled:
        raise ApiError(404, "dev_login_disabled")
    try:
        user = auth.dev_login(settings, request.app.state.engine, body.email, body.password)
    except auth.InvalidCredentialsError as e:
        raise ApiError(401, "invalid_credentials") from e
    token = auth.dev_tokens(settings).issue(user)
    return TokenOut(access_token=token, expires_in=settings.jwt_ttl_minutes * 60)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(_: Annotated[Actor, Depends(require(Permission.ACCOUNT_READ))]) -> Response:
    """Tokens are stateless until Cognito (S29): the client drops its token. This confirms the token was valid."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
def password_reset(body: PasswordResetIn) -> Response:
    """A stub, like the prototype's toast. Always 202, so it never reveals whether an email exists."""
    return Response(status_code=status.HTTP_202_ACCEPTED)
