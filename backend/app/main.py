import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import console, conversations, demo, health, kb, tenants
from app.config import get_settings
from app.core.redis_client import get_redis_client
from app.services import maintenance


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    task = None
    if settings.maintenance_enabled:
        task = asyncio.create_task(maintenance.run_forever(get_redis_client(), settings))
    try:
        yield
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Triagent", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # the demo token travels in Authorization, never in a cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(tenants.router, prefix="/api")
    app.include_router(demo.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(console.router, prefix="/api")
    app.include_router(kb.router, prefix="/api")

    return app


app = create_app()
