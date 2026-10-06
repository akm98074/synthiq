"""The standard question set asked about every user message."""
from __future__ import annotations

from .types import Question, choice, noul, score

INTENT = choice(
    "intent",
    "What does the user want from the assistant with this message?",
    {
        "chit_chat": "small talk, greetings, thanks, feelings, banter",
        "quick_answer": "a factual question, explanation or advice, or looking something up "
                        "(prices, shops, restaurants, opening hours, weather, news)",
        "task": "write, draft, plan, summarise, rewrite or produce something",
        "schedule": "set a reminder, plan a time, check or change the calendar",
        "memory_write": "the user is telling the assistant something about themselves to remember",
        "memory_query": "the user asks what the assistant knows or remembers about them",
        "computer_action": "operate apps, files, browser, email or devices on the computer",
    },
)

NEEDS_MEMORY_WRITE = noul(
    "needs_memory_write",
    "Does the message contain a durable personal fact or preference worth remembering?",
)

COMPLEXITY = score(
    "complexity",
    "How much reasoning does a good reply need?",
    ["trivial one-liner", "short answer", "a few steps", "multi-step reasoning", "long, hard task"],
)

STANDARD: list[Question] = [INTENT, NEEDS_MEMORY_WRITE, COMPLEXITY]

# Questions whose confidence decides whether the fast path escalates.
GATING = ("intent", "needs_memory_write")

BY_NAME = {q.name: q for q in STANDARD}


# ── Proactive triage: "is this worth interrupting the user for?" ──────────
SHOULD_NUDGE = noul(
    "should_nudge",
    "Is this item worth interrupting the user about now (needs their reply or action soon)?",
)

URGENCY = score(
    "urgency",
    "How urgent is it for the user?",
    ["can wait for weeks", "this week", "in the next day or two", "today", "right now"],
)

NUDGE_QUESTIONS: list[Question] = [SHOULD_NUDGE, URGENCY]
NUDGE_GATING = ("should_nudge",)
BY_NAME.update({q.name: q for q in NUDGE_QUESTIONS})
