"""Composition root: wires infrastructure singletons via dependency-injector."""

from dependency_injector import containers, providers

from database import DatabaseSettings, create_engine, create_session_factory
from dedup.config import DedupSettings
from shared.cache.config import CacheSettings
from shared.cache.factory import CacheProviderFactory
from shared.queue.provider import create_job_queue
from shared.storage.config import StorageSettings
from shared.storage.factory import StorageProviderFactory
from upload.config import UploadSettings
from variants.config import VariantSettings


class Container(containers.DeclarativeContainer):
    storage_settings = providers.Singleton(StorageSettings)

    # `providers.Singleton` is lazy — it only runs on first access. The app's
    # startup/lifespan must call `container.storage_provider()` eagerly so
    # config errors surface early.
    storage_provider = providers.Singleton(
        StorageProviderFactory.create,
        settings=storage_settings,
    )

    cache_settings = providers.Singleton(CacheSettings)

    # Same eager-init note as storage_provider: call `container.cache_provider()`
    # during startup/lifespan so a bad REDIS_URL fails fast instead of on first request.
    cache_provider = providers.Singleton(
        CacheProviderFactory.create,
        settings=cache_settings,
    )

    database_settings = providers.Singleton(DatabaseSettings)

    # Same eager-init note as storage_provider: call `container.db_engine()` during
    # startup/lifespan so a bad DATABASE_URL fails fast instead of on first request.
    db_engine = providers.Singleton(create_engine, settings=database_settings)

    db_session_factory = providers.Singleton(create_session_factory, engine=db_engine)

    upload_settings = providers.Singleton(UploadSettings)

    dedup_settings = providers.Singleton(DedupSettings)

    variant_settings = providers.Singleton(VariantSettings)

    # Same eager-init note as storage_provider/cache_provider: call
    # `container.job_queue()` during startup/lifespan so a bad REDIS_URL fails
    # fast instead of on first upload.
    job_queue = providers.Singleton(
        create_job_queue,
        redis_url=cache_settings.provided.redis_url,
    )


container = Container()
