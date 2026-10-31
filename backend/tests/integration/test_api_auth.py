"""Dev login, token checks and the public endpoints (12 §7, S03 decisions)."""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine

from konboro.api.app import create_app
from konboro.services.auth import AUDIENCE, ISSUER
from konboro.settings import Settings

from .api import DEV_PASSWORD, Api, add_tenant, api_settings, bearer


def login(api: Api, email: str, password: str = DEV_PASSWORD):  # type: ignore[no-untyped-def]
    return api.client.post("/auth/login", json={"email": email, "password": password})


def test_health_is_public(api: Api) -> None:
    response = api.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_gives_a_token_with_cognito_shaped_claims(api: Api) -> None:
    response = login(api, api.a.email.upper())  # email is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == api.settings.jwt_ttl_minutes * 60
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sub"] == api.a.user_id
    assert claims["email"] == api.a.email
    assert claims["custom:tenant_id"] == api.a.tenant_id
    assert claims["custom:role"] == "owner"


def test_wrong_password_and_unknown_email_get_the_same_answer(api: Api) -> None:
    wrong = login(api, api.a.email, "nope")
    unknown = login(api, "nobody@nowhere.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"] == {"code": "invalid_credentials", "message": "האימייל או הסיסמה לא נכונים"}


def test_email_in_directory_but_not_in_the_tenant_is_refused(api: Api) -> None:
    # The directory points at tenant A, but A has no such user: never fall through to another tenant.
    settings = api_settings([api.a]).model_copy(update={"dev_users": f"ghost@x.test={api.a.tenant_id}"})
    with TestClient(create_app(settings, engine=api.engine)) as client:
        response = client.post("/auth/login", json={"email": "ghost@x.test", "password": DEV_PASSWORD})
    assert response.status_code == 401


def test_login_without_a_configured_password_is_refused(api: Api) -> None:
    settings = api_settings([api.a]).model_copy(update={"dev_password": None})
    with TestClient(create_app(settings, engine=api.engine)) as client:
        response = client.post("/auth/login", json={"email": api.a.email, "password": ""})
        assert response.status_code == 422  # empty password fails validation first
        response = client.post("/auth/login", json={"email": api.a.email, "password": "anything"})
    assert response.status_code == 401


def test_login_can_be_turned_off(api: Api) -> None:
    settings = api_settings([api.a]).model_copy(update={"dev_login_enabled": False})
    with TestClient(create_app(settings, engine=api.engine)) as client:
        response = client.post("/auth/login", json={"email": api.a.email, "password": DEV_PASSWORD})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dev_login_disabled"


def test_dev_login_cannot_be_on_in_production() -> None:
    try:
        Settings(env="production", dev_login_enabled=True)
    except ValueError as e:
        assert "dev login must be off" in str(e)
    else:
        raise AssertionError("expected a validation error")
    assert Settings(env="production", dev_login_enabled=False).env == "production"


def test_short_signing_keys_are_refused() -> None:
    try:
        Settings(jwt_secret=SecretStr("short"))
    except ValueError as e:
        assert "at least 32 bytes" in str(e)
    else:
        raise AssertionError("expected a validation error")


def test_validation_errors_never_echo_the_password(api: Api) -> None:
    response = api.client.post("/auth/login", json={"email": "not-an-email", "password": "hunter2-secret"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "hunter2-secret" not in response.text


def test_token_then_me_then_logout(api: Api) -> None:
    token = login(api, api.a.email).json()["access_token"]
    assert api.client.get("/me", headers=bearer(token)).json()["tenant"]["id"] == api.a.tenant_id
    assert api.client.post("/auth/logout", headers=bearer(token)).status_code == 204


def test_password_reset_is_a_public_stub(api: Api) -> None:
    for email in (api.a.email, "nobody@nowhere.test"):
        assert api.client.post("/auth/password-reset", json={"email": email}).status_code == 202


def _forge(api: Api, **changes: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": api.a.user_id,
        "email": api.a.email,
        "custom:tenant_id": api.a.tenant_id,
        "custom:role": "owner",
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(changes)
    secret = str(claims.pop("_secret", api.settings.jwt_secret.get_secret_value()))
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, algorithm="HS256")


def test_bad_tokens_are_401(api: Api) -> None:
    now = datetime.now(UTC)
    bad = {
        "wrong signature": _forge(api, _secret="someone-elses-secret-of-enough-length"),
        "expired": _forge(api, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1)),
        "wrong audience": _forge(api, aud="other"),
        "wrong issuer": _forge(api, iss="other"),
        "no tenant": _forge(api, **{"custom:tenant_id": None}),
        "bad tenant id": _forge(api, **{"custom:tenant_id": "tenant-a"}),
        "unknown user": _forge(api, sub="usr_01JD0NOBODY000000000000000"),
        "user of another tenant": _forge(api, sub=api.b.user_id),
        "garbage": "not.a.token",
    }
    for name, token in bad.items():
        response = api.client.get("/me", headers=bearer(token))
        assert response.status_code == 401, name
        assert response.json()["error"]["code"] == "unauthorized", name
        assert response.headers["www-authenticate"] == "Bearer", name


def test_the_db_role_counts_not_the_token_role(api: Api) -> None:
    # A token claiming another role still gets the user's DB role.
    response = api.client.get("/me", headers=bearer(_forge(api, **{"custom:role": "admin"})))
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "owner"


def test_suspended_tenant_is_403(api: Api, migrated_db: dict[str, Engine]) -> None:
    suspended = add_tenant(migrated_db["app"], status="suspended")
    response = api.client.get("/me", headers=api.as_(suspended))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "tenant_suspended"


def test_cors_allows_the_vite_origin_only(api: Api) -> None:
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
    ok = api.client.options("/me", headers={"Origin": "http://localhost:5180", **preflight})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5180"
    other = api.client.options("/me", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in other.headers


def test_secret_is_never_in_settings_repr() -> None:
    settings = Settings(dev_password=SecretStr("pw-value"), jwt_secret=SecretStr("jwt-value-" + "x" * 32))
    assert "pw-value" not in repr(settings)
    assert "jwt-value" not in repr(settings)
