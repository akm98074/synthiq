"""
ARQ WorkerSettings — defines what functions the worker exposes and how it
connects to Redis.

Run the worker with:
    python -m arq workers.settings.WorkerSettings
"""
from __future__ import annotations

import logging

import anthropic
from arq.connections import RedisSettings

from config import settings
from workers.ingest import ingest_source

log = logging.getLogger(__name__)


async def on_startup(ctx: dict) -> None:
    """Called once when the worker process starts."""
    log.info("Worker starting up…")
    ctx["anthropic_client"] = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key
    )
    log.info("Worker ready — connected to Redis at %s", settings.redis_url)


async def on_shutdown(ctx: dict) -> None:
    """Called once when the worker process shuts down."""
    log.info("Worker shutting down")


class WorkerSettings:
    functions = [ingest_source]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 3600        # 1 hour max per job
    keep_result = 86400       # keep job results for 24 h
    retry_jobs = True
    max_tries = 3
