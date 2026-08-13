"""Composition root: wires infrastructure singletons via dependency-injector."""

from dependency_injector import containers, providers

from shared.storage.config import StorageSettings
from shared.storage.factory import StorageProviderFactory


class Container(containers.DeclarativeContainer):
    storage_settings = providers.Singleton(StorageSettings)

    # `providers.Singleton` is lazy — it only runs on first access. The app's
    # startup/lifespan must call `container.storage_provider()` eagerly so config errors surface early.
    storage_provider = providers.Singleton(
        StorageProviderFactory.create,
        settings=storage_settings,
    )
