"""Model manager: what's configured, installed, loaded, and how much RAM is free."""
from __future__ import annotations

import psutil

from ..config import Settings
from .ollama import OllamaClient, OllamaError, model_present

GB = 1024 ** 3

# Rough resident sizes (GB) for the defaults, used for budget hints in the UI.
APPROX_SIZE_GB = {
    "qwen3:4b": 2.6,
    "qwen3:8b": 5.2,
    "qwen3:1.7b": 1.4,
    "gemma3:4b": 3.3,
    "all-minilm": 0.05,
}


def configured_models(s: Settings) -> list[dict]:
    return [
        {"role": "chat", "name": s.chat_model},
        {"role": "fast / judge", "name": s.fast_model},
        {"role": "embeddings", "name": s.embed_model},
    ]


def ram() -> dict:
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / GB, 1),
        "available_gb": round(vm.available / GB, 1),
        "used_percent": vm.percent,
    }


async def status(client: OllamaClient, s: Settings) -> dict:
    out: dict = {"ram": ram(), "configured": configured_models(s), "ollama": None,
                 "installed": [], "loaded": [], "error": None}
    try:
        out["ollama"] = await client.version()
        installed = await client.tags()
        loaded = await client.ps()
    except OllamaError as exc:
        out["error"] = str(exc)
        return out
    out["installed"] = [
        {"name": m.get("name"), "size_gb": round(m.get("size", 0) / GB, 2)} for m in installed
    ]
    out["loaded"] = [
        {"name": m.get("name"), "size_gb": round(m.get("size", 0) / GB, 2),
         "vram_gb": round(m.get("size_vram", 0) / GB, 2), "expires_at": m.get("expires_at")}
        for m in loaded
    ]
    for m in out["configured"]:
        m["installed"] = model_present(m["name"], installed)
        m["approx_gb"] = APPROX_SIZE_GB.get(m["name"])
    return out
