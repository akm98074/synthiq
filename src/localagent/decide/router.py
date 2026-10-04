"""Decision router: the first call made on every input.

hybrid (default): prototype classifier first. If a gating question is below
the confidence threshold, it escalates to the SLM judge.
prototype: prototype only (fastest).
slm: SLM judge only (slowest, used as a baseline in evals).
systemone: external Jev-style server; falls back to hybrid on error.
"""
from __future__ import annotations

import logging
import time

from ..memory.store import Store
from .prototype import PrototypeClassifier
from .questions import BY_NAME, GATING, STANDARD
from .slm_judge import SLMJudge
from .systemone import SystemOneClient
from .types import Answer, Decision, Question, answer_from_probs

log = logging.getLogger(__name__)


def _uniform(q: Question) -> Answer:
    return answer_from_probs(q, {l: 1.0 for l in q.labels})


class DecisionRouter:
    def __init__(
        self,
        store: Store,
        prototype: PrototypeClassifier,
        judge: SLMJudge,
        systemone: SystemOneClient | None,
        backend: str = "hybrid",
        threshold: float = 0.6,
        questions: list[Question] | None = None,
    ):
        self.store = store
        self.prototype = prototype
        self.judge = judge
        self.systemone = systemone
        self.backend = backend
        self.threshold = threshold
        self.questions = questions or STANDARD

    def _needs_escalation(self, answers: dict[str, Answer]) -> bool:
        for name in GATING:
            ans = answers.get(name)
            if ans is None or ans.confidence < self.threshold:
                return True
        return False

    async def decide(
        self, text: str, context: str = "", log_it: bool = True, backend: str | None = None
    ) -> Decision:
        backend = backend or self.backend
        start = time.perf_counter()
        notes: list[str] = []
        escalated = False
        answers: dict[str, Answer] = {}
        used = backend

        if backend == "systemone":
            if self.systemone is not None:
                try:
                    answers = await self.systemone.decide(text, self.questions)
                except Exception as exc:  # noqa: BLE001 - fall back on any failure
                    notes.append(f"systemone failed ({exc.__class__.__name__}); fell back to hybrid")
            # Fill gaps / low-confidence answers with the built-in hybrid path.
            backend = "hybrid" if (not answers or self._needs_escalation(answers)) else "done"
            used = "systemone" if answers else "prototype"

        if backend in ("hybrid", "prototype"):
            proto = await self.prototype.decide(text, self.questions)
            for k, v in proto.items():
                answers.setdefault(k, v)
            if used not in ("systemone",):
                used = "prototype"
            if backend == "hybrid" and self._needs_escalation(answers):
                try:
                    judged = await self.judge.decide(text, self.questions, context, prior=answers)
                    answers.update(judged)
                    escalated = True
                    used = f"{used}+slm"
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"slm escalation failed: {exc}")
        elif backend == "slm":
            answers = await self.judge.decide(text, self.questions, context)
            used = "slm"

        for q in self.questions:
            if q.name not in answers:
                answers[q.name] = _uniform(q)
                notes.append(f"{q.name}: no answer, used uniform prior")

        decision = Decision(
            text=text,
            answers=answers,
            backend=used,
            latency_ms=(time.perf_counter() - start) * 1000,
            escalated=escalated,
            notes=notes,
        )
        if log_it:
            decision.id = self.store.log_decision(decision.to_dict())
        return decision

    async def correct(self, decision_id: int, question: str, label: str) -> None:
        q = BY_NAME.get(question)
        if q is None or label not in q.options:
            raise ValueError(f"Unknown question/label: {question}={label}")
        row = self.store.get_decision(decision_id)
        if row is None:
            raise KeyError(decision_id)
        self.store.add_correction(decision_id, question, label)
        vec = (await self.prototype.embed([row["text"]]))[0]
        self.store.add_example(
            question, label, row["text"], source="user",
            embedding=vec, embed_model=self.prototype.embed_model,
        )
        self.prototype.invalidate()
