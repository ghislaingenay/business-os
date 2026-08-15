"""Unit tests for the arq task boundary (`worker.tasks.generate_variants`).

Verifies the retry/backoff wiring (FR-3) without a real arq worker or Redis —
`VariantService.generate` itself is covered by tests/variants/test_service.py.
"""

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry

from variants.config import VariantSettings
from variants.exceptions import VariantGenerationError
from worker.tasks import generate_variants

_FILE_ID = str(uuid.uuid4())
_STORAGE_KEY = "originals/2026/08/15/abc.jpg"
_MIME_TYPE = "image/jpeg"


def _make_ctx(job_try: int) -> dict:
    @asynccontextmanager
    async def _session_cm():
        yield MagicMock()

    return {
        "variant_settings": VariantSettings(
            web_optimized_quality=85,
            thumbnail_size=256,
            thumbnail_quality=80,
            job_timeout_seconds=60,
            retry_delays_seconds=(1, 5, 25),
            generated_mime_types=("image/jpeg", "image/png", "image/gif"),
        ),
        "storage_provider": MagicMock(),
        "db_session_factory": MagicMock(side_effect=_session_cm),
        "job_try": job_try,
    }


@pytest.mark.parametrize(("job_try", "expected_defer"), [(1, 1), (2, 5), (3, 25)])
async def test_generate_variants_retries_with_configured_backoff(
    job_try: int, expected_defer: int
) -> None:
    ctx = _make_ctx(job_try)

    with (
        patch(
            "worker.tasks.VariantService.generate",
            new=AsyncMock(side_effect=VariantGenerationError("boom")),
        ),
        pytest.raises(Retry) as exc_info,
    ):
        await generate_variants(ctx, _FILE_ID, _STORAGE_KEY, _MIME_TYPE)

    assert exc_info.value.defer_score == expected_defer * 1000


async def test_generate_variants_gives_up_after_retries_exhausted() -> None:
    ctx = _make_ctx(job_try=4)

    with (
        patch(
            "worker.tasks.VariantService.generate",
            new=AsyncMock(side_effect=VariantGenerationError("boom")),
        ),
        pytest.raises(VariantGenerationError),
    ):
        await generate_variants(ctx, _FILE_ID, _STORAGE_KEY, _MIME_TYPE)


async def test_generate_variants_calls_service_with_parsed_args() -> None:
    ctx = _make_ctx(job_try=1)

    with patch(
        "worker.tasks.VariantService.generate", new=AsyncMock(return_value=None)
    ) as mock_generate:
        await generate_variants(ctx, _FILE_ID, _STORAGE_KEY, _MIME_TYPE)

    mock_generate.assert_awaited_once_with(uuid.UUID(_FILE_ID), _STORAGE_KEY, _MIME_TYPE)
