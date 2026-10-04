"""Optional backend: an external Jev-style decision server.

Targets servers speaking a System-One style API (e.g. Ollaya or `von serve`)
on localhost. The wire format of these young projects is not yet stable, so
the request is sent in a common shape and the response parser accepts the
variants seen so far. This backend is EXPERIMENTAL: if it fails, the router
falls back to the built-in backends and records a note on the decision.
"""
from __future__ import annotations

import httpx

from .types import Answer, Question, answer_from_probs


def build_request(text: str, questions: list[Question]) -> dict:
    qs = []
    for q in questions:
        item: dict = {"name": q.name, "type": q.kind, "question": q.prompt}
        if q.kind in ("choice", "score"):
            item["choices"] = dict(q.options)
        qs.append(item)
    return {"state": text, "questions": qs}


def parse_response(data: dict, questions: list[Question]) -> dict[str, Answer]:
    by_name = {q.name: q for q in questions}
    raw = data.get("answers", data.get("decisions", data))
    items: list[tuple[str, dict]] = []
    if isinstance(raw, list):
        items = [(a.get("name", ""), a) for a in raw if isinstance(a, dict)]
    elif isinstance(raw, dict):
        items = [(k, v) for k, v in raw.items() if isinstance(v, dict)]
    out: dict[str, Answer] = {}
    for name, item in items:
        q = by_name.get(name)
        if q is None:
            continue
        probs = item.get("probabilities") or item.get("probs")
        if q.kind == "noul" and probs is None:
            p = item.get("probability", item.get("p"))
            if p is not None:
                probs = {"yes": float(p), "no": 1 - float(p)}
        if isinstance(probs, dict):
            probs = {str(k).lower() if q.kind == "noul" else str(k): float(v)
                     for k, v in probs.items()}
            probs = {"yes" if k == "true" else "no" if k == "false" else k: v
                     for k, v in probs.items()}
            out[name] = answer_from_probs(q, probs)
    return out


class SystemOneClient:
    name = "systemone"

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def decide(self, text: str, questions: list[Question]) -> dict[str, Answer]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v1/systemone", json=build_request(text, questions)
            )
            resp.raise_for_status()
            return parse_response(resp.json(), questions)
