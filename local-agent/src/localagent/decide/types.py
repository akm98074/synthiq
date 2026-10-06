"""Typed decision questions, mirroring the Jev / System-One vocabulary.

choice -> pick one of K described options
noul   -> calibrated yes/no
score  -> position on an ordinal scale (1..N)

Every question is answered as a probability distribution over string labels,
so all backends share one representation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Kind = Literal["choice", "noul", "score"]


@dataclass(frozen=True)
class Question:
    name: str
    kind: Kind
    prompt: str
    options: dict[str, str]  # label -> description

    @property
    def labels(self) -> list[str]:
        return list(self.options)


def choice(name: str, prompt: str, options: dict[str, str]) -> Question:
    return Question(name, "choice", prompt, options)


def noul(name: str, prompt: str) -> Question:
    return Question(name, "noul", prompt, {"yes": "true", "no": "false"})


def score(name: str, prompt: str, scale: list[str]) -> Question:
    return Question(name, "score", prompt, {str(i + 1): d for i, d in enumerate(scale)})


@dataclass
class Answer:
    name: str
    kind: Kind
    label: str
    probs: dict[str, float]

    @property
    def confidence(self) -> float:
        return self.probs.get(self.label, 0.0)

    @property
    def yes(self) -> bool:
        return self.label == "yes"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["confidence"] = round(self.confidence, 4)
        d["probs"] = {k: round(v, 4) for k, v in self.probs.items()}
        return d


def answer_from_probs(q: Question, probs: dict[str, float]) -> Answer:
    total = sum(max(probs.get(l, 0.0), 0.0) for l in q.labels) or 1.0
    norm = {l: max(probs.get(l, 0.0), 0.0) / total for l in q.labels}
    label = max(norm, key=norm.get)
    return Answer(q.name, q.kind, label, norm)


@dataclass
class Decision:
    text: str
    answers: dict[str, Answer]
    backend: str
    latency_ms: float
    escalated: bool = False
    id: int | None = None
    notes: list[str] = field(default_factory=list)

    def __getitem__(self, name: str) -> Answer:
        return self.answers[name]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "backend": self.backend,
            "latency_ms": round(self.latency_ms, 1),
            "escalated": self.escalated,
            "notes": self.notes,
            "answers": {k: a.to_dict() for k, a in self.answers.items()},
        }
