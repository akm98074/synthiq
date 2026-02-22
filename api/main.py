"""
Synthiq FastAPI application entry point.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import projects, sources, synthesis, voice

app = FastAPI(
    title="Synthiq API",
    version="1.0.0",
    description="Research Synthesis & Knowledge Management",
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

app.include_router(projects.router)
app.include_router(sources.router)
app.include_router(synthesis.router)
app.include_router(voice.router)


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}
