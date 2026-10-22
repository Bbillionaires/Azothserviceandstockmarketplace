"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    admin,
    admin_finance,
    agreements,
    auth,
    creators,
    earnings,
    galleries,
    library,
    licenses,
    media,
    messages,
    orders,
    production,
    public_config,
    search,
    trust,
)
from app.core.config import get_settings
from app.services.storage import LocalStorage, get_storage

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.brand_name} API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    for module in (auth, creators, agreements, media, search, licenses, library, trust, orders, earnings, production,
                   messages, galleries, admin, admin_finance, public_config):
        app.include_router(module.router, prefix=settings.api_prefix)

    @app.get("/health", tags=["ops"])
    def health():
        return {"status": "ok"}

    # Development only: serve watermarked public renditions from local disk.
    # Originals live in a separate private directory that is never mounted.
    storage = get_storage()
    if isinstance(storage, LocalStorage):
        app.mount("/media-public", StaticFiles(directory=storage.root / "public"), name="media-public")

    return app


app = create_app()
