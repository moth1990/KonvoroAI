"""The FastAPI app. `uvicorn --factory konboro.api.app:create_app` (make dev), or `create_app(...)` in tests."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from konboro.db.session import app_engine
from konboro.services import auth, flags, viewer
from konboro.services.queue import Queue
from konboro.services.storage import Storage
from konboro.settings import Settings, get_settings

from . import errors
from .routes import account, drawings, health, home, pages, quotes
from .routes import auth as auth_routes
from .routes import settings as settings_routes

ROUTERS = (
    health.router,
    auth_routes.router,
    account.router,
    settings_routes.router,
    home.router,
    drawings.router,
    quotes.router,
    pages.router,
)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    verifier: auth.TokenVerifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    local = settings.env != "production"
    app = FastAPI(
        title="Konboro API",
        version="0.1.0",
        docs_url="/docs" if local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if local else None,
    )
    app.state.settings = settings
    app.state.engine = engine or app_engine()
    app.state.verifier = verifier or auth.dev_tokens(settings)
    app.state.storage = Storage(settings)
    app.state.queue = Queue(settings)
    app.state.tile_indexes = viewer.TileIndexes()
    flags.cache.ttl = settings.flag_cache_seconds

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    errors.install(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
