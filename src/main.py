"""FastAPI application entrypoint and composition root wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from container import container
from exceptions import register_exception_handlers
from shared.logging.middleware import RequestIDMiddleware
from upload.router import router as upload_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Eager singleton init: fail fast on bad config instead of on first request.
    # logging_configured runs first so every other singleton's own setup can
    # log through the fully-configured structlog pipeline.
    container.logging_configured()
    container.storage_provider()
    container.cache_provider()
    container.db_engine()
    container.job_queue()
    yield


app = FastAPI(title="Business OS", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
register_exception_handlers(app)
app.include_router(upload_router)
