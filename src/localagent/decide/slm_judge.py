"""Escalation backend: a small generative model answers the questions as JSON.

Output is constrained with Ollama's JSON-schema `format`, so it is always
parseable. Generative models don't expose calibrated probabilities through
this API, so the judge's label gets a fixed weight and the remaining mass is
spread using the prototype's distribution when one is available. The
`localagent eval decision` command measures how well calibrated that is.
"""
from __future__ import annotations

from ..llm.ollama import OllamaClient
from .types import Answer, Question, answer_from_probs

JUDGE_WEIGHT = 0.8


def build_schema(questions: list[Question]) -> dict:
    props = {q.name: {"type": "string", "enum": q.labels} for q in questions}
    return {"type": "object", "properties": props, "required": list(props)}


def build_prompt(text: str, questions: list[Question], context: str = "") -> str:
    lines = [
        "You are a fast decision module inside a personal assistant.",
        "Classify the user's latest message by answering each question with one allowed label.",
        "",
    ]
    for q in questions:
        lines.append(f"## {q.name} ({q.kind}): {q.prompt}")
        for label, desc in q.options.items():
            lines.append(f"- {label}: {desc}")
        lines.append("")
    if context:
        lines += ["## Recent conversation", context, ""]
    lines += ["## Latest user message", text, "", "Reply with JSON only."]
    return "\n".join(lines)


class SLMJudge:
    name = "slm"

    def __init__(self, client: OllamaClient, model: str):
        self.client = client
        self.model = model

    async def decide(
        self,
        text: str,
        questions: list[Question],
        context: str = "",
        prior: dict[str, Answer] | None = None,
    ) -> dict[str, Answer]:
        result = await self.client.chat_json(
            self.model,
            [{"role": "user", "content": build_prompt(text, questions, context)}],
            build_schema(questions),
        )
        out: dict[str, Answer] = {}
        for q in questions:
            label = result.get(q.name)
            if label not in q.options:
                if prior and q.name in prior:
                    out[q.name] = prior[q.name]
                continue
            base = prior[q.name].probs if prior and q.name in prior else {
                l: 1.0 / len(q.labels) for l in q.labels
            }
            probs = {
                l: (1 - JUDGE_WEIGHT) * base.get(l, 0.0) + (JUDGE_WEIGHT if l == label else 0.0)
                for l in q.labels
            }
            out[q.name] = answer_from_probs(q, probs)
        return out
