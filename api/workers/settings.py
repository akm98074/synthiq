"""
ARQ WorkerSettings — defines what functions the worker exposes and how it
connects to Redis.

Run the worker with:
    python -m arq workers.settings.WorkerSettings
"""
from __future__ import annotations

import logging

import anthropic
from arq.connections import RedisSettings, create_pool

from config import settings
from workers.ingest import ingest_source
from workers.index_project import index_project
from workers.generate_deliverable import generate_deliverable

log = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    """Called once when the worker process starts."""
    log.info("Worker starting up…")
    ctx["anthropic_client"] = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key
    )
    # ARQ pool in ctx so ingest_source can enqueue index_project
    ctx["arq_pool"] = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    log.info("Worker ready — connected to Redis at %s", settings.redis_url)


async def on_shutdown(ctx: dict) -> None:
    """Called once when the worker process shuts down."""
    arq_pool = ctx.get("arq_pool")
    if arq_pool:
        await arq_pool.aclose()
    log.info("Worker shutting down")


class WorkerSettings:
    functions = [ingest_source, index_project, generate_deliverable]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 3600        # 1 hour max per job
    keep_result = 86400       # keep job results for 24 h
    retry_jobs = True
    max_tries = 3
