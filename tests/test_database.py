from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from database import DatabaseSettings, create_engine, create_session_factory

_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/db"


def test_create_engine_returns_async_engine_for_configured_url() -> None:
    settings = DatabaseSettings(database_url=_DATABASE_URL)

    engine = create_engine(settings)

    assert isinstance(engine, AsyncEngine)
    assert engine.url.render_as_string(hide_password=False) == _DATABASE_URL


def test_create_session_factory_returns_async_sessionmaker_bound_to_engine() -> None:
    engine = create_engine(DatabaseSettings(database_url=_DATABASE_URL))

    session_factory = create_session_factory(engine)

    assert isinstance(session_factory, async_sessionmaker)
    assert session_factory.kw["bind"] is engine
