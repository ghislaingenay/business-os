"""Composition root: wires infrastructure singletons via dependency-injector."""

from dependency_injector import containers, providers

from database import DatabaseSettings, create_engine, create_session_factory
from shared.storage.config import StorageSettings
from shared.storage.factory import StorageProviderFactory
from upload.config import UploadSettings


class Container(containers.DeclarativeContainer):
    storage_settings = providers.Singleton(StorageSettings)

    # `providers.Singleton` is lazy — it only runs on first access. The app's
    # startup/lifespan must call `container.storage_provider()` eagerly so
    # config errors surface early.
    storage_provider = providers.Singleton(
        StorageProviderFactory.create,
        settings=storage_settings,
    )

    database_settings = providers.Singleton(DatabaseSettings)

    # Same eager-init note as storage_provider: call `container.db_engine()` during
    # startup/lifespan so a bad DATABASE_URL fails fast instead of on first request.
    db_engine = providers.Singleton(create_engine, settings=database_settings)

    db_session_factory = providers.Singleton(create_session_factory, engine=db_engine)

    upload_settings = providers.Singleton(UploadSettings)


container = Container()
