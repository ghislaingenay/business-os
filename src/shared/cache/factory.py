"""Factory for instantiating a `CacheProvider` from configuration."""

from shared.cache.config import CacheSettings
from shared.cache.provider import CacheProvider
from shared.cache.redis_provider import RedisCacheProvider


class CacheProviderFactory:
    """Builds the configured `CacheProvider`."""

    @staticmethod
    def create(settings: CacheSettings) -> CacheProvider:
        return RedisCacheProvider(redis_url=settings.redis_url)
