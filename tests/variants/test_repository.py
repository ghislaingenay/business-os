"""Unit tests for `VariantRepository` against a mocked `AsyncSession`.

Mirrors `tests/upload/test_repository.py`'s convention: no real Postgres,
just verifying what gets executed/committed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from variants.repository import VariantRepository


@pytest.fixture()
def mock_session() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


async def test_update_variants_executes_and_commits(mock_session: MagicMock) -> None:
    repo = VariantRepository(mock_session)
    file_id = uuid.uuid4()

    await repo.update_variants(
        file_id,
        web_optimized_url="webp/2026/08/15/abc.webp",
        thumbnail_url="thumbnails/2026/08/15/abc_thumb.jpg",
    )

    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
