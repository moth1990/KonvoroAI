"""Route audit (00 §14.1): every route except the public ones depends on `current_actor`, and really refuses
a request without a token. A new router that forgets the dependency fails here."""

import re

import pytest
from fastapi import routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from sqlalchemy import create_engine

from konboro.api.app import create_app
from konboro.api.deps import PUBLIC_ROUTES, current_actor
from konboro.settings import Settings

from .api import Api

SETTINGS = Settings(_env_file=None, env="test")  # type: ignore[call-arg]
APP = create_app(SETTINGS, engine=create_engine("postgresql+psycopg://unused@localhost/unused"))
# Included routers are wrapped; iter_route_contexts yields each effective route (FastAPI's OpenAPI uses it too).
ROUTES = [
    (method, str(ctx.path), ctx.original_route)
    for ctx in routing.iter_route_contexts(APP.routes)
    if isinstance(ctx.original_route, APIRoute)
    for method in sorted(ctx.original_route.methods)
]


def uses_actor(dependant: Dependant) -> bool:
    return any(d.call is current_actor or uses_actor(d) for d in dependant.dependencies)


def test_there_are_routes_to_audit() -> None:
    assert len(ROUTES) >= 7
    assert {(m, p) for m, p, _ in ROUTES} >= PUBLIC_ROUTES, "a public route was renamed: update PUBLIC_ROUTES"


@pytest.mark.parametrize(("method", "path", "route"), ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_every_private_route_requires_an_actor(method: str, path: str, route: APIRoute) -> None:
    if (method, path) in PUBLIC_ROUTES:
        assert not uses_actor(route.dependant)
    else:
        assert uses_actor(route.dependant), f"{method} {path} must depend on require(...)"


@pytest.mark.parametrize(
    ("method", "path"),
    [(m, p) for m, p, _ in ROUTES if (m, p) not in PUBLIC_ROUTES],
    ids=[f"{m} {p}" for m, p, _ in ROUTES if (m, p) not in PUBLIC_ROUTES],
)
def test_every_private_route_answers_401_without_a_token(api: Api, method: str, path: str) -> None:
    url = re.sub(r"\{[^}]+\}", "x", path)
    response = api.client.request(method, url, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_the_audit_catches_an_unguarded_route() -> None:
    router = routing.APIRouter()

    @router.get("/leaky")
    def leaky() -> dict[str, str]:
        return {}

    [route] = [r for r in router.routes if isinstance(r, APIRoute)]
    assert not uses_actor(route.dependant)
