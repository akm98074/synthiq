"""
Synthiq FastAPI application entry point.
"""
from __future__ import annotations

import logging
import pathlib
import tempfile
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import settings
from routers import billing, projects, sources, synthesis, voice

log = logging.getLogger(__name__)


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create ARQ Redis pool on startup; close on shutdown."""
    try:
        app.state.arq_pool = await create_pool(
            RedisSettings.from_dsn(settings.redis_url)
        )
        log.info("ARQ Redis pool connected: %s", settings.redis_url)
    except Exception as exc:
        log.warning("Could not connect ARQ pool (jobs will be skipped): %s", exc)
        app.state.arq_pool = None

    yield

    if app.state.arq_pool:
        await app.state.arq_pool.aclose()


# ─── App ──────────────────────────────────────────────────────────────────────


app = FastAPI(
    title="Synthiq API",
    version="1.0.0",
    description="Research Synthesis & Knowledge Management",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://synthiq.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(billing.router)
app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(synthesis.router)
app.include_router(voice.router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def health():
    arq_ok = app.state.arq_pool is not None
    return {
        "status": "ok",
        "version": "1.0.0",
        "queue": "connected" if arq_ok else "disconnected",
    }


# ─── Local export download (dev mode, no S3) ──────────────────────────────────


@app.get("/export-download/{token}/{filename}", tags=["export"])
async def serve_export(token: str, filename: str):
    """
    Serve a locally-stored export file.

    Used when AWS S3 is not configured (development mode).
    The file is stored in the OS temp directory by the export endpoint.
    """
    export_dir = pathlib.Path(tempfile.gettempdir()) / "synthiq-exports"
    path = export_dir / f"{token}_{filename}"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export not found or expired")

    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".docx"):
        media_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        media_type = "application/octet-stream"

    return FileResponse(path=str(path), media_type=media_type, filename=filename)
