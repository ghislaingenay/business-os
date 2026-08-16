"""Unit tests for repository classes against a mocked `AsyncSession`.

No real Postgres needed here — these test the repositories' own logic
(what gets added/committed/mutated), not persistence itself, which this
project's test suite doesn't exercise against a live DB anywhere else either
(see tests/test_database.py for the same convention).
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from upload.models import File, MultipartSession, UploadSession
from upload.repository import FileRepository, MultipartSessionRepository, UploadSessionRepository


@pytest.fixture()
def mock_session() -> MagicMock:
    # `AsyncSession.add()` is synchronous; only commit/refresh/execute are
    # async. A bare AsyncMock() would make `add` async too, producing
    # "coroutine was never awaited" warnings since the real code never
    # awaits it.
    session = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


def _make_file() -> File:
    return File(
        storage_key="originals/2026/08/14/abc.jpg",
        filename="profile.jpg",
        size=1024,
        mime_type="image/jpeg",
        upload_strategy="mediated",
    )


def _make_session() -> UploadSession:
    return UploadSession(
        filename="video.mp4",
        size=5_000_000,
        mime_type="video/mp4",
        presigned_url="https://s3.example.com/bucket/key",
        storage_key="originals/2026/08/14/abc.mp4",
        expires_at=datetime.now(UTC),
        finalized=False,
    )


async def test_file_repository_save_adds_commits_and_refreshes(mock_session: MagicMock) -> None:
    repo = FileRepository(mock_session)
    file = _make_file()

    result = await repo.save(file)

    mock_session.add.assert_called_once_with(file)
    mock_session.commit.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(file)
    assert result is file


async def test_upload_session_repository_save_adds_commits_and_refreshes(
    mock_session: MagicMock,
) -> None:
    repo = UploadSessionRepository(mock_session)
    session_row = _make_session()

    result = await repo.save(session_row)

    mock_session.add.assert_called_once_with(session_row)
    mock_session.commit.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(session_row)
    assert result is session_row


async def test_mark_finalized_mutates_without_committing(mock_session: MagicMock) -> None:
    """Regression test for the finalize_large_upload atomicity fix.

    mark_finalized must NOT call commit() on its own — UploadService relies
    on FileRepository.save()'s single commit right after to persist both
    changes atomically on the shared per-request AsyncSession. If this method
    starts committing again, that atomicity guarantee silently breaks.
    """
    repo = UploadSessionRepository(mock_session)
    session_row = _make_session()

    await repo.mark_finalized(session_row)

    assert session_row.finalized is True
    mock_session.commit.assert_not_called()


async def test_find_active_by_id_returns_matching_session(mock_session: MagicMock) -> None:
    repo = UploadSessionRepository(mock_session)
    expected = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_session.execute.return_value = result

    found = await repo.find_active_by_id(uuid.uuid4())

    assert found is expected


async def test_find_active_by_id_returns_none_when_missing(mock_session: MagicMock) -> None:
    repo = UploadSessionRepository(mock_session)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = result

    found = await repo.find_active_by_id(uuid.uuid4())

    assert found is None


def _make_multipart_session() -> MultipartSession:
    return MultipartSession(
        storage_upload_id="s3-upload-id",
        filename="video.mp4",
        size=524_288_000,
        mime_type="video/mp4",
        part_size=10_485_760,
        total_parts=50,
        storage_key="originals/2026/08/16/abc.mp4",
        finalized=False,
        expires_at=datetime.now(UTC),
    )


async def test_multipart_session_repository_save_adds_commits_and_refreshes(
    mock_session: MagicMock,
) -> None:
    repo = MultipartSessionRepository(mock_session)
    session_row = _make_multipart_session()

    result = await repo.save(session_row)

    mock_session.add.assert_called_once_with(session_row)
    mock_session.commit.assert_awaited_once()
    mock_session.refresh.assert_awaited_once_with(session_row)
    assert result is session_row


async def test_multipart_find_active_by_id_returns_matching_session(
    mock_session: MagicMock,
) -> None:
    repo = MultipartSessionRepository(mock_session)
    expected = _make_multipart_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    mock_session.execute.return_value = result

    found = await repo.find_active_by_id(uuid.uuid4())

    assert found is expected


async def test_multipart_mark_finalized_mutates_without_committing(
    mock_session: MagicMock,
) -> None:
    repo = MultipartSessionRepository(mock_session)
    session_row = _make_multipart_session()

    await repo.mark_finalized(session_row)

    assert session_row.finalized is True
    mock_session.commit.assert_not_called()


async def test_find_expired_unfinalized_returns_matching_sessions(
    mock_session: MagicMock,
) -> None:
    repo = MultipartSessionRepository(mock_session)
    expected = [_make_multipart_session()]
    result = MagicMock()
    result.scalars.return_value.all.return_value = expected
    mock_session.execute.return_value = result

    found = await repo.find_expired_unfinalized(datetime.now(UTC))

    assert found == expected


async def test_multipart_delete_removes_and_commits(mock_session: MagicMock) -> None:
    repo = MultipartSessionRepository(mock_session)
    session_row = _make_multipart_session()

    await repo.delete(session_row)

    mock_session.delete.assert_awaited_once_with(session_row)
    mock_session.commit.assert_awaited_once()
