"""One chat turn: decide → (remember) → recall → respond (streamed).

Yields events consumed by the HTTP layer as server-sent events:
  {"type": "decision", "decision": {...}}
  {"type": "memory_saved", "memory": {...}, "updated": bool}
  {"type": "recalled", "memories": [...]}
  {"type": "token", "text": "..."}
  {"type": "error", "message": "..."}
  {"type": "tool_start" | "tool_result" | "approval_required", ...}   (action intents)
  {"type": "done", "message_id": int, "model": str}
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, AsyncIterator

from ..llm.ollama import RESET, OllamaError
from ..memory.store import MEMORY_KINDS
from ..persona import system_prompt
from ..tools.registry import candidates
from .actions import ACTION_INTENTS, ActionRun, tools_prompt
from .cloud import build_request, cloud_tool, stream_answer, wants_cloud

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


# Pure writing tasks ("draft a toast") and general questions stream straight from the
# model; tasks and questions only go through the tool loop when they mention something a
# connector can touch ("any unread email?", "newest PDF in Downloads").
TOOL_HINTS = re.compile(
    r"\b(calendar|meeting|event|remind|reminders?|notes?|mail|e-?mail|inbox|send|files?|folders?|"
    r"downloads?|desktop|documents?|pdf|spreadsheet|excel|xlsx|contacts?|phone number|save|"
    r"messages?|imessages?|texts?|sms|whatsapp|chats?|repl(y|ies|ied)|browser|website|web ?page|"
    r"site|url|online|google|search the web|skills?|screen|window|apps?|shortcuts?|forms?|fill in|"
    r"button|click|press)\b|https?://|www\.|\.(com|org|net|io)\b",
    re.IGNORECASE,
)


def wants_tools(intent: str, text: str, skill_words: tuple[str, ...] = (), web: bool = False) -> bool:
    if intent in ("schedule", "computer_action"):
        return True
    if intent == "quick_answer" and web:
        return True     # the model decides whether the answer needs a fresh look-up
    if intent not in (*ACTION_INTENTS, "quick_answer"):
        return False
    low = text.lower()
    return bool(TOOL_HINTS.search(text)) or any(w in low for w in skill_words)


def pick_model(rt: "Runtime", intent: str, complexity: int) -> str:
    s = rt.settings
    if intent in ("chit_chat", "memory_write") and complexity <= 2:
        return s.fast_model
    return s.chat_model


PHONE_NOTE = ("\nYou are on a phone call: answer in a few short spoken sentences, no lists or links. On the "
              "phone you can only look things up and prepare drafts; if asked to send, change or delete "
              "something, say the user needs to approve it in the app.")


async def handle_turn(rt: "Runtime", text: str, channel: str = "app") -> AsyncIterator[dict]:
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

    past = [{"role": m["role"], "content": m["content"]} for m in history
            if m["role"] in ("user", "assistant")]

    if channel != "phone" and wants_cloud(rt, text, complexity):
        req = build_request(rt, text, history, memories)
        tool = cloud_tool(rt)
        args = {k: req[k] for k in ("question", "memories", "history_turns")}
        if rt.policy.needs_approval(tool, user_msg_id, args=args):
            ap = rt.policy.request(tool, args, user_msg_id, {"kind": "cloud", "req": req})
            rt.audit.append("approval_requested", tool.name, tool.tier, args, "pending", ap["summary"],
                            ap["id"], user_msg_id)
            ap.pop("state", None)
            yield {"type": "approval_required", "approval": ap}
            yield {"type": "done", "message_id": None, "model": s.chat_model, "paused": True}
            return
        async for event in _ask_cloud(rt, req, user_msg_id, None, decision.id):
            yield event
        return

    skill_words = tuple(t.name[6:].replace("_", " ") for t in rt.tools.values() if t.connector == "skills")
    web = "web_search" in rt.tools
    tools = candidates(rt.tools, intent) if wants_tools(intent, text, skill_words, web) else []
    if channel == "phone":   # by phone only look-ups and drafts: nothing can be approved there
        tools = [t for t in tools if t.tier in ("read", "draft")]
    note = PHONE_NOTE if channel == "phone" else ""
    if tools:
        messages = [{"role": "system",
                     "content": system_prompt(s, "task", memories, with_tools=True) + "\n\n" + tools_prompt()
                     + note}]
        messages += past + [{"role": "user", "content": text}]
        run = ActionRun(rt, user_msg_id, tools, messages, s.chat_model)
        async for event in run.start():
            yield event
        msg_id = rt.store.add_message("assistant", run.final_text, decision.id) if run.final_text else None
        yield {"type": "done", "message_id": msg_id, "model": s.chat_model, "paused": run.paused}
        return

    model = pick_model(rt, intent, complexity)
    messages = [{"role": "system", "content": system_prompt(s, intent, memories) + note}]
    messages += past
    messages.append({"role": "user", "content": text})

    reply: list[str] = []
    try:
        async for piece in rt.ollama.chat_stream(model, messages):
            if RESET in piece:
                reply.clear()
                yield {"type": "reset"}
                piece = piece.split(RESET)[-1]
                if not piece:
                    continue
            reply.append(piece)
            yield {"type": "token", "text": piece}
    except OllamaError as exc:
        yield {"type": "error", "message": str(exc)}
    full = "".join(reply).strip()
    msg_id = rt.store.add_message("assistant", full, decision.id) if full else None
    yield {"type": "done", "message_id": msg_id, "model": model}


async def _ask_cloud(rt: "Runtime", req: dict, task_id: int, approval_id: int | None,
                     decision_id: int | None) -> AsyncIterator[dict]:
    model = rt.settings.cloud_model
    args = {k: req[k] for k in ("question", "memories", "history_turns")}
    yield {"type": "tool_start", "tool": "cloud_ask", "tier": "write",
           "summary": f"Asking {model} in the cloud"}
    parts: list[str] = []
    failed = False
    async for ev in stream_answer(rt, req):
        if ev["type"] == "token":
            parts.append(ev["text"])
        else:
            failed = True
        yield ev
    yield {"type": "tool_result", "tool": "cloud_ask", "tier": "write", "ok": not failed,
           "display": f"Answered by {model} (cloud)" if not failed else "Cloud request failed", "data": None}
    rt.audit.append("tool_call", "cloud_ask", "write", args, "error" if failed else "ok",
                    f"{model}: {len(''.join(parts))} characters back", approval_id, task_id)
    full = "".join(parts).strip()
    msg_id = rt.store.add_message("assistant", full, decision_id) if full else None
    yield {"type": "done", "message_id": msg_id, "model": f"{model} (cloud)", "cloud": True}


async def resume_after_decision(rt: "Runtime", approval: dict, approved: bool) -> AsyncIterator[dict]:
    """Continue a paused action run once the user approved or declined."""
    state = approval.get("state")
    if not state:
        yield {"type": "error", "message": "This request can no longer be resumed."}
        return
    if state.get("kind") == "cloud":
        if approved:
            async for event in _ask_cloud(rt, state["req"], approval["task_id"], approval["id"], None):
                yield event
        else:
            text = "OK, nothing was sent. Ask again without “think harder” for an answer from this Mac."
            yield {"type": "token", "text": text}
            yield {"type": "done", "message_id": rt.store.add_message("assistant", text), "model": None}
        return
    run = ActionRun.from_state(rt, approval["task_id"], state)
    async for event in run.resume(approval, approved):
        yield event
    msg_id = rt.store.add_message("assistant", run.final_text) if run.final_text else None
    yield {"type": "done", "message_id": msg_id, "model": run.model, "paused": run.paused}
