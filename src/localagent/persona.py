"""System prompt construction from persona settings, memories and intent."""
from __future__ import annotations

from datetime import datetime

from .config import Settings
from .memory.store import Memory

INTENT_GUIDANCE = {
    "chit_chat": "Reply naturally and briefly, like a friendly assistant over text.",
    "quick_answer": "Answer directly and accurately. Lead with the answer; keep it short unless asked.",
    "task": "Produce the requested output carefully. Use structure (lists, headings) when it helps.",
    "schedule": (
        "You cannot create reminders or calendar events right now (the Calendar/Reminders "
        "connectors are off or unavailable on this computer). Help the user pin down the "
        "details and say they can enable the connector in the Connectors tab."
    ),
    "computer_action": (
        "You cannot do this action right now: no enabled connector covers it (browser and "
        "general app control arrive in a later version). Explain briefly how the user could "
        "do it, or draft what they need."
    ),
    "memory_write": (
        "The user shared something about themselves. Acknowledge in one short sentence what "
        "you will remember. Do not lecture."
    ),
    "memory_query": (
        "Answer from the remembered facts below only. If nothing relevant is remembered, say "
        "so honestly and invite the user to tell you."
    ),
}


def system_prompt(settings: Settings, intent: str, memories: list[Memory],
                  with_tools: bool = False) -> str:
    who = f" The user's name is {settings.user_name}." if settings.user_name else ""
    parts = [
        f"You are {settings.agent_name}, a personal assistant running entirely on the user's "
        f"own computer. Your tone is {settings.tone}.{who}",
        f"Current local time: {datetime.now().strftime('%A %d %B %Y, %H:%M')}.",
    ]
    if not with_tools:
        parts.append(INTENT_GUIDANCE.get(intent, INTENT_GUIDANCE["quick_answer"]))
    if memories:
        facts = "\n".join(f"- ({m.kind}) {m.text}" for m in memories)
        parts.append(
            "Things you remember about the user (use them when relevant, never invent more):\n"
            + facts
        )
    return "\n\n".join(parts)
