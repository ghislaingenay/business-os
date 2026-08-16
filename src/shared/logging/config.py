"""Structured logging configuration (structlog) — FR-1, FR-2 (TD-007 §3).

Configures JSON logs in production and human-readable console logs in local
development, driven by `LOG_LEVEL`/`LOG_FORMAT` env vars. `configure_logging()`
is wired into `container.py` as a Singleton (`container.logging_configured()`),
matching the composition root's existing eager-init pattern for
`storage_provider`/`cache_provider`/`db_engine`/`job_queue` — `main.py`'s
`lifespan` calls it before anything else so structlog is configured before
any request or log line. Domain modules get their logger via `setup_logger()`
in place of stdlib's `logging.getLogger(__name__)`.
"""

import logging
from typing import Literal, cast

import structlog
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    """Env-driven logging config."""

    # `populate_by_name=True`: mirrors `dedup.config.DedupSettings` — field
    # names (`level`, `format`) differ from their env var aliases
    # (`LOG_LEVEL`, `LOG_FORMAT`), so both must be accepted for tests to
    # construct this by plain field name.
    model_config = SettingsConfigDict(case_sensitive=False, populate_by_name=True)

    level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    format: Literal["json", "console"] = Field(default="json", validation_alias="LOG_FORMAT")


def _uppercase_level(
    _logger: object, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    # structlog's `add_log_level` emits lowercase ("info", "error"); FR-1's
    # schema example uses uppercase ("INFO", "ERROR").
    event_dict["level"] = event_dict["level"].upper()
    return event_dict


def configure_logging(settings: LoggingSettings) -> None:
    """Configure structlog process-wide. Called once via
    `container.logging_configured()`.

    `format="console"` renders human-readable output for local development;
    `format="json"` (production default) renders the JSON body FR-1's
    acceptance criteria describe. `merge_contextvars` is what makes
    `request_id` (bound by `RequestIDMiddleware`) appear on every log
    statement made within a request's async context, satisfying FR-2's
    "Logged: Included in every log statement".

    Log lines carry their message under structlog's native `event` field
    (no `EventRenamer` to `message`) — `shared.logging.metrics`'s helpers
    rely on this: their metric name (`"dedup_check"`, etc.) IS the log
    call's positional message, so it has to land under `event` to match
    FR-3's own query examples (`WHERE event = 'dedup_check'`). A
    `.bind(event=...)` alongside the positional message can't produce a
    second, distinct field — structlog sets both under the same `event` key,
    and the positional one wins — so there's no way to have both a
    `message`-named prose field and an `event`-named metric-name field for
    the same call; `event` was chosen since FR-3's metrics are the
    field's operationally load-bearing consumer.
    """
    renderer = (
        structlog.dev.ConsoleRenderer()
        if settings.format == "console"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            _uppercase_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.level.upper()]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        # Deliberately NOT cache_logger_on_first_use=True: every domain module
        # calls `setup_logger(__name__)` at import time, which happens before
        # `container.logging_configured()` runs `configure_logging()` at
        # app/worker startup — caching on first log call would permanently
        # lock those loggers onto whatever structlog's pre-configuration
        # default renderer is, ignoring this configuration entirely.
        cache_logger_on_first_use=False,
    )


def setup_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    """Return a structlog logger, bound with `logger_name` so log lines carry
    which module emitted them. Use in place of stdlib's
    `logging.getLogger(__name__)`:

        logger = setup_logger(__name__)

    Relies on `container.logging_configured()` having already run during
    app/worker startup (see module docstring) — this function itself does
    no configuration.

    `logger_name` is passed as an initial value to `get_logger()` rather
    than via a `.bind()` call: every domain module calls this at import
    time, before `configure_logging()` has run — `.bind()` on structlog's
    lazy proxy materializes a concrete logger immediately, using whatever
    (unconfigured) processors are active at that moment, and permanently
    ignores any `configure_logging()` call that happens afterward.
    `get_logger(**initial_values)` stays lazy instead, resolving the actual
    processor chain on each call.
    """
    initial_values = {} if name is None else {"logger_name": name}
    return cast(structlog.typing.FilteringBoundLogger, structlog.get_logger(**initial_values))
