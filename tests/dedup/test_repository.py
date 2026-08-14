"""Unit tests for `DedupRepository` against a mocked `AsyncSession` — no real
Postgres needed, mirroring tests/upload/test_repository.py's convention.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from dedup.exceptions import DedupDatabaseUnavailableError
from dedup.repository import DedupRepository

_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_STORAGE_KEY = "originals/2026/08/14/abc.jpg"
_TIMEOUT = 5


@pytest.fixture()
def mock_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    return session


async def test_find_storage_key_by_hash_returns_match(mock_session: MagicMock) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = _STORAGE_KEY
    mock_session.execute.return_value = result
    repo = DedupRepository(mock_session, query_timeout_seconds=_TIMEOUT)

    found = await repo.find_storage_key_by_hash(_HASH)

    assert found == _STORAGE_KEY


async def test_find_storage_key_by_hash_returns_none_when_missing(
    mock_session: MagicMock,
) -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result
    repo = DedupRepository(mock_session, query_timeout_seconds=_TIMEOUT)

    found = await repo.find_storage_key_by_hash(_HASH)

    assert found is None


async def test_find_storage_key_by_hash_raises_on_timeout(mock_session: MagicMock) -> None:
    # A plain async function, not AsyncMock: AsyncMock's `return_value` isn't
    # itself awaited when set to a coroutine, so it can't be used to simulate
    # a query that actually takes time to resolve.
    async def _slow_execute(*_args: object, **_kwargs: object) -> MagicMock:
        await asyncio.sleep(10)
        return MagicMock()

    mock_session.execute = _slow_execute
    repo = DedupRepository(mock_session, query_timeout_seconds=0.01)

    with pytest.raises(DedupDatabaseUnavailableError):
        await repo.find_storage_key_by_hash(_HASH)
