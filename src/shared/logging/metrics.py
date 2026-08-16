"""Structured metric-event log helpers (FR-3, FR-5; TD-007 §3, §5).

Each helper's positional log message IS the metric name (`"dedup_check"`,
etc.) — `configure_logging` doesn't rename structlog's native `event` field,
so it lands in the JSON output as `event`, matching FR-3's own query
examples (`WHERE event = 'dedup_check'`). Extra fields are bound first via
`.bind()`. Callers pass already-computed values; these helpers own only the
event name and field shape, not any business logic — kept in `shared/` per
`context/coding-standards.md` §12 (business-agnostic technical capability),
not a domain package.
"""

from shared.logging.config import setup_logger

logger = setup_logger(__name__)

_DEDUP_CHECK_EVENT = "dedup_check"
_UPLOAD_COMPLETE_EVENT = "upload_complete"
_VARIANT_GENERATED_EVENT = "variant_generated"

_HASH_LOG_TRUNCATE_LEN = 16


def log_dedup_check(
    *,
    result: str,
    sha256_hash: str,
    latency_ms: float,
    source: str | None = None,
    file_size: int | None = None,
) -> None:
    """Log a `dedup_check` event (FR-3).

    `result` is `"hit"`, `"miss"`, or `"error"` — unified into one event
    family (FEAT-007 §FR-3, resolved 2026-08-16) so FR-3's hit-rate query
    filters on a single event name instead of needing a separate
    `database_unavailable` event for the error case. `result="error"` logs
    at ERROR level (FR-4's "Error Tracking"); hit/miss log at INFO.
    """
    bound = logger.bind(
        result=result,
        hash=sha256_hash[:_HASH_LOG_TRUNCATE_LEN],
        latency_ms=round(latency_ms, 2),
        source=source,
        file_size=file_size,
    )
    if result == "error":
        bound.error(_DEDUP_CHECK_EVENT)
    else:
        bound.info(_DEDUP_CHECK_EVENT)


def log_upload_complete(*, file_id: str, size: int, strategy: str, duration_ms: float) -> None:
    """Log an `upload_complete` event (FR-3, FR-5's `upload_duration_ms`)."""
    logger.bind(
        file_id=file_id,
        size=size,
        strategy=strategy,
        duration_ms=round(duration_ms, 2),
        outcome="success",
    ).info(_UPLOAD_COMPLETE_EVENT)


def log_variant_generated(
    *, file_id: str, variant_type: str, duration_ms: float, outcome: str = "success"
) -> None:
    """Log a `variant_generated` event (FR-3, FR-5's
    `variant_generation_duration_ms`).
    """
    logger.bind(
        file_id=file_id,
        variant_type=variant_type,
        duration_ms=round(duration_ms, 2),
        outcome=outcome,
    ).info(_VARIANT_GENERATED_EVENT)
