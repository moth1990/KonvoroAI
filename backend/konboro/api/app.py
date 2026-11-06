"""The FastAPI app. `uvicorn --factory konboro.api.app:create_app` (make dev), or `create_app(...)` in tests."""

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from konboro.db.session import app_engine
from konboro.services import auth, flags, viewer
from konboro.services.llm import chat_providers
from konboro.services.queue import Queue
from konboro.services.storage import Storage
from konboro.settings import Settings, get_settings

from . import errors
from .routes import (
    account,
    audits,
    chat,
    document,
    drawings,
    export,
    health,
    home,
    knowledge,
    onboarding,
    pages,
    price_list,
    quotes,
)
from .routes import auth as auth_routes
from .routes import settings as settings_routes

ROUTERS = (
    health.router,
    auth_routes.router,
    account.router,
    settings_routes.router,
    document.router,
    home.router,
    drawings.router,
    quotes.router,
    export.router,
    pages.router,
    audits.router,
    price_list.router,
    onboarding.router,
    knowledge.router,
    chat.router,
)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    verifier: auth.TokenVerifier | None = None,
    llm_providers: dict[str, Any] | None = None,
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
    # The chat's model (08): Claude with a key; the stand-in in tests and locally without one (services.llm)
    app.state.llm_providers = llm_providers if llm_providers is not None else chat_providers(settings)
    flags.cache.ttl = settings.flag_cache_seconds

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],  # an export's file name (S26)
    )
    errors.install(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
