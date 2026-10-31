from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import console, conversations, health, kb, tenants
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Triagent")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(tenants.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(console.router, prefix="/api")
    app.include_router(kb.router, prefix="/api")

    return app


app = create_app()
