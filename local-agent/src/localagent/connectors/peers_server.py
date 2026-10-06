"""The agent-to-agent listener: one route, encrypted messages from paired agents only."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request

if TYPE_CHECKING:
    from ..runtime import Runtime


def a2a_app(rt: "Runtime") -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/a2a/v1/inbox")
    async def inbox(request: Request) -> dict:
        try:
            envelope = await request.json()
            if not isinstance(envelope, dict) or len(str(envelope)) > 64_000:
                raise PermissionError("malformed message")
            return await rt.peers.handle(envelope)
        except PermissionError as exc:
            rt.audit.append("peer_rejected", "peers", outcome="rejected",
                            detail=f"{request.client.host if request.client else '?'}: {exc}")
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, "malformed message") from exc

    return app
