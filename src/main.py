"""FastAPI application entrypoint and composition root wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from container import container
from exceptions import register_exception_handlers
from upload.router import router as upload_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Eager singleton init: fail fast on bad config instead of on first request.
    container.storage_provider()
    container.db_engine()
    yield


app = FastAPI(title="Business OS", lifespan=lifespan)
register_exception_handlers(app)
app.include_router(upload_router)
