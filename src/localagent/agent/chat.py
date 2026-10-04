"""One chat turn: decide → (remember) → recall → respond (streamed).

Yields events consumed by the HTTP layer as server-sent events:
  {"type": "decision", "decision": {...}}
  {"type": "memory_saved", "memory": {...}, "updated": bool}
  {"type": "recalled", "memories": [...]}
  {"type": "token", "text": "..."}
  {"type": "error", "message": "..."}
  {"type": "done", "message_id": int, "model": str}
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncIterator

from ..llm.ollama import OllamaError
from ..memory.store import MEMORY_KINDS
from ..persona import system_prompt

if TYPE_CHECKING:
    from ..runtime import Runtime

log = logging.getLogger(__name__)

HISTORY_TURNS = 10
DEDUP_SIMILARITY = 0.92

FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
                },
                "required": ["text", "kind"],
            },
        }
    },
    "required": ["facts"],
}

FACT_PROMPT = """Extract durable facts about the USER from their message, for a personal memory.
Rules:
- Only things likely to stay true for weeks or more (preferences, relationships, places, routines, personal facts).
- Write each fact as a short third-person statement, e.g. "Prefers window seats on flights."
- Use kind: preference | fact | person | place | routine.
- If there is nothing durable, return an empty list.

Message: {text}"""


def _format_history(messages: list[dict]) -> str:
    return "\n".join(f"{m['role']}: {m['content'][:300]}" for m in messages[-6:])


async def remember(rt: "Runtime", text: str, source_message_id: int | None) -> list[dict]:
    s = rt.settings
    result = await rt.ollama.chat_json(
        s.fast_model,
        [{"role": "user", "content": FACT_PROMPT.format(text=text)}],
        FACT_SCHEMA,
    )
    facts = [f for f in result.get("facts", []) if str(f.get("text", "")).strip()][:5]
    if not facts:
        return []
    vecs = await rt.embed([f["text"] for f in facts])
    saved = []
    for fact, vec in zip(facts, vecs):
        existing = rt.store.search_memories(vec, s.embed_model, k=1, min_score=DEDUP_SIMILARITY)
        if existing:
            mem_id = existing[0].id
            rt.store.update_memory(mem_id, text=fact["text"], kind=fact.get("kind"),
                                   embedding=vec, embed_model=s.embed_model)
            updated = True
        else:
            mem_id = rt.store.add_memory(fact["text"], fact.get("kind", "fact"), vec,
                                         s.embed_model, source_message_id)
            updated = False
        mem = rt.store.get_memory(mem_id)
        saved.append({"memory": mem.to_dict(), "updated": updated})
    rt.write_identity()
    return saved


def pick_model(rt: "Runtime", intent: str, complexity: int) -> str:
    s = rt.settings
    if intent in ("chit_chat", "memory_write") and complexity <= 2:
        return s.fast_model
    return s.chat_model


async def handle_turn(rt: "Runtime", text: str) -> AsyncIterator[dict]:
    s = rt.settings
    history = rt.store.recent_messages(HISTORY_TURNS * 2)
    user_msg_id = rt.store.add_message("user", text)

    try:
        decision = await rt.router.decide(text, context=_format_history(history))
    except OllamaError as exc:
        yield {"type": "error", "message": str(exc)}
        return
    rt.store.set_message_decision(user_msg_id, decision.id)
    yield {"type": "decision", "decision": decision.to_dict()}

    intent = decision["intent"].label
    complexity = int(decision["complexity"].label)

    if intent == "memory_write" or decision["needs_memory_write"].yes:
        try:
            for item in await remember(rt, text, user_msg_id):
                yield {"type": "memory_saved", **item}
        except OllamaError as exc:
            yield {"type": "error", "message": f"Could not save memory: {exc}"}

    k = s.memory_top_k * 2 if intent == "memory_query" else s.memory_top_k
    min_score = 0.0 if intent == "memory_query" else s.memory_min_similarity
    try:
        qvec = (await rt.embed([text]))[0]
        memories = rt.store.search_memories(qvec, s.embed_model, k=k, min_score=min_score)
    except OllamaError:
        memories = []
    if memories:
        yield {"type": "recalled", "memories": [m.to_dict() for m in memories]}

    model = pick_model(rt, intent, complexity)
    messages = [{"role": "system", "content": system_prompt(s, intent, memories)}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history
                 if m["role"] in ("user", "assistant")]
    messages.append({"role": "user", "content": text})

    reply: list[str] = []
    try:
        async for piece in rt.ollama.chat_stream(model, messages):
            reply.append(piece)
            yield {"type": "token", "text": piece}
    except OllamaError as exc:
        yield {"type": "error", "message": str(exc)}
    full = "".join(reply).strip()
    msg_id = rt.store.add_message("assistant", full, decision.id) if full else None
    yield {"type": "done", "message_id": msg_id, "model": model}
