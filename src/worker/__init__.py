"""arq worker configuration (TD-004 §3, §8; TD-005 §7).

Run with `arq worker.WorkerSettings` (see `make worker`). Reuses `container`
(the same composition root `main.py` wires the FastAPI app from) so the
worker process shares config parsing and provider-construction logic with
the API process instead of duplicating it.
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from arq.worker import Function, func

from container import container
from worker.tasks import cleanup_abandoned_multipart_sessions, generate_variants


async def startup(ctx: dict[str, Any]) -> None:
    # Per-job dependencies are built from these in `worker.tasks` rather than
    # stored as already-connected clients here, since `max_jobs` concurrent
    # jobs share this one `ctx` dict and a `AsyncSession` isn't safe to share
    # across concurrent tasks.
    ctx["storage_provider"] = container.storage_provider()
    ctx["db_session_factory"] = container.db_session_factory()
    ctx["variant_settings"] = container.variant_settings()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(container.cache_settings().redis_url)
    functions: ClassVar[list[Function]] = [func(generate_variants, max_tries=4)]
    cron_jobs: ClassVar[list[CronJob]] = [cron(cleanup_abandoned_multipart_sessions, hour=2)]
    on_startup = startup
    max_jobs = 10
    job_timeout = container.variant_settings().job_timeout_seconds
