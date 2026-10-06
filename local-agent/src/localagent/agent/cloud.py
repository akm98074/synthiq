"""Optional cloud escalation: ask Claude (your own Anthropic API key) when the local model
isn't enough. Off by default; nothing is sent without an approval card that says exactly
what will leave this Mac.

When it's used:
  - you ask for it ("think harder", "use cloud", "ask Claude"), or
  - (optional setting) the decision layer rates the question as hardest (complexity 5).

What's sent: your message, the last few turns of the conversation, and (setting) the
memories recalled for this message. No tools run in the cloud, and nothing else on the Mac
is reachable from there.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, AsyncIterator

from ..tools.base import Tool, ToolResult, obj

if TYPE_CHECKING:
    from ..memory.store import Memory
    from ..runtime import Runtime

KEY = "anthropic_api_key"
ASK = re.compile(r"\b(think harder|think (it )?through carefully|use (the )?cloud|ask claude|cloud model)\b",
                 re.IGNORECASE)
CLOUD_HINT = re.compile(r"^\s*(please\s+)?(think harder|use (the )?cloud|ask claude)[\s,:.-]*", re.IGNORECASE)
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def wants_cloud(rt: "Runtime", text: str, complexity: int) -> bool:
    s = rt.settings
    if not (s.cloud_enabled and rt.vault.has(KEY)):
        return False
    return bool(ASK.search(text)) or (s.cloud_auto_hard and complexity >= 5)


def cloud_tool(rt: "Runtime") -> Tool:
    """Not offered to the model: it exists so the policy engine (approvals, scopes, audit) gates
    what leaves the Mac, exactly like any other write action."""
    def summary(a: dict) -> str:
        extra = []
        if a.get("memories"):
            extra.append(f"{a['memories']} memories")
        if a.get("history_turns"):
            extra.append(f"{a['history_turns']} earlier messages")
        return (f"Send to {rt.settings.cloud_model} (Anthropic, cloud): “{a.get('question', '')[:120]}”"
                + (f" + {', '.join(extra)}" if extra else ""))

    return Tool("cloud_ask", "Ask the cloud model", obj({}), "write", "cloud",
                lambda a: ToolResult("", ""), summary, ())


def build_request(rt: "Runtime", text: str, history: list[dict], memories: list["Memory"]) -> dict:
    from ..persona import system_prompt

    s = rt.settings
    mems = memories if s.cloud_send_memories else []
    question = CLOUD_HINT.sub("", text).strip() or text
    past = [{"role": m["role"], "content": m["content"]} for m in history[-6:]
            if m["role"] in ("user", "assistant") and m["content"]]
    while past and past[0]["role"] != "user":
        past.pop(0)
    return {"system": system_prompt(s, "quick_answer", mems),
            "messages": past + [{"role": "user", "content": question}],
            "question": question, "memories": len(mems), "history_turns": len(past)}


async def stream_answer(rt: "Runtime", req: dict) -> AsyncIterator[dict]:
    """Stream the cloud answer as token events (and an error event on failure)."""
    try:
        import anthropic
    except ImportError:
        yield {"type": "error", "message": "The cloud add-on isn't installed. In Terminal run: "
                                           "pipx inject localaiagent anthropic"}
        return
    s = rt.settings
    client = anthropic.AsyncAnthropic(api_key=rt.vault.get(KEY), base_url=rt.cloud_base_url, max_retries=2)
    try:
        async with client.beta.messages.stream(
            model=s.cloud_model, max_tokens=16000, system=req["system"], messages=req["messages"],
            output_config={"effort": s.cloud_effort},
            betas=[FALLBACK_BETA], fallbacks="default",     # a safety decline is retried server-side
        ) as stream:
            async for text in stream.text_stream:
                yield {"type": "token", "text": text}
            final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            yield {"type": "error", "message": "The cloud model declined to answer this one."}
        elif final.stop_reason == "max_tokens":
            yield {"type": "token", "text": "\n\n(The answer was cut short.)"}
    except anthropic.AuthenticationError:
        yield {"type": "error", "message": "Anthropic rejected the API key. Set it again in Settings → Cloud."}
    except anthropic.PermissionDeniedError:
        yield {"type": "error", "message": "This API key can't use that model. Check Settings → Cloud."}
    except anthropic.RateLimitError:
        yield {"type": "error", "message": "The cloud model is rate-limited right now. Try again in a minute."}
    except anthropic.APIStatusError as exc:
        yield {"type": "error", "message": f"Cloud error ({exc.status_code}): {exc.message}"}
    except anthropic.APIConnectionError:
        yield {"type": "error", "message": "Couldn't reach Anthropic. Check the internet connection."}
    finally:
        await client.close()
