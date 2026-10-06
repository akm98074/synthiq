"""Phase-0 gate: how accurate, calibrated and fast is the decision layer?

Input: JSONL rows like {"text": "...", "intent": "task", "memory": false}.
Columns map to questions the same way as the seed file (see prototype.SEED_COLUMNS).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..decide.prototype import SEED_COLUMNS, load_jsonl
from ..decide.router import DecisionRouter

EVAL_FILE = "decision_eval.jsonl"
GATE_ACCURACY = 0.90
GATE_ECE = 0.05


@dataclass
class QuestionResult:
    name: str
    y_true: list[str] = field(default_factory=list)
    y_pred: list[str] = field(default_factory=list)
    conf: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.y_true)

    def accuracy(self) -> float:
        return sum(t == p for t, p in zip(self.y_true, self.y_pred)) / self.n if self.n else 0.0

    def macro_f1(self) -> float:
        labels = sorted(set(self.y_true) | set(self.y_pred))
        f1s = []
        for label in labels:
            tp = sum(t == label and p == label for t, p in zip(self.y_true, self.y_pred))
            fp = sum(t != label and p == label for t, p in zip(self.y_true, self.y_pred))
            fn = sum(t == label and p != label for t, p in zip(self.y_true, self.y_pred))
            prec = tp / (tp + fp) if tp + fp else 0.0
            rec = tp / (tp + fn) if tp + fn else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
        return sum(f1s) / len(f1s) if f1s else 0.0

    def ece(self, bins: int = 10) -> float:
        """Expected calibration error of the top-label confidence."""
        if not self.n:
            return 0.0
        total = 0.0
        for b in range(bins):
            lo, hi = b / bins, (b + 1) / bins
            idx = [i for i, c in enumerate(self.conf) if (lo < c <= hi) or (b == 0 and c == 0)]
            if not idx:
                continue
            acc = sum(self.y_true[i] == self.y_pred[i] for i in idx) / len(idx)
            conf = sum(self.conf[i] for i in idx) / len(idx)
            total += len(idx) / self.n * abs(acc - conf)
        return total

    def confusions(self, top: int = 5) -> list[tuple[str, str, int]]:
        counts: dict[tuple[str, str], int] = {}
        for t, p in zip(self.y_true, self.y_pred):
            if t != p:
                counts[(t, p)] = counts.get((t, p), 0) + 1
        return sorted(((t, p, c) for (t, p), c in counts.items()), key=lambda x: -x[2])[:top]

    def summary(self) -> dict:
        return {
            "question": self.name,
            "n": self.n,
            "accuracy": round(self.accuracy(), 4),
            "macro_f1": round(self.macro_f1(), 4),
            "ece": round(self.ece(), 4),
            "top_confusions": [{"true": t, "pred": p, "count": c} for t, p, c in self.confusions()],
        }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def load_rows(path: Path | None) -> list[dict]:
    if path is None:
        return load_jsonl(EVAL_FILE)
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


async def run(
    router: DecisionRouter,
    rows: list[dict],
    backend: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    results: dict[str, QuestionResult] = {}
    latencies: list[float] = []
    escalations = 0
    for i, row in enumerate(rows):
        decision = await router.decide(row["text"], log_it=False, backend=backend)
        latencies.append(decision.latency_ms)
        escalations += int(decision.escalated)
        for column, (question, fmt) in SEED_COLUMNS.items():
            if column not in row or question not in decision.answers:
                continue
            ans = decision.answers[question]
            res = results.setdefault(question, QuestionResult(question))
            res.y_true.append(fmt(row[column]))
            res.y_pred.append(ans.label)
            res.conf.append(ans.confidence)
        if progress:
            progress(i + 1, len(rows))

    summaries = [r.summary() for r in results.values()]
    intent = results.get("intent")
    gate = None
    if intent and intent.n:
        gate = {
            "accuracy_target": GATE_ACCURACY,
            "ece_target": GATE_ECE,
            "passed": intent.accuracy() >= GATE_ACCURACY and intent.ece() <= GATE_ECE,
        }
    return {
        "backend": backend or router.backend,
        "rows": len(rows),
        "questions": summaries,
        "latency_ms": {
            "p50": round(percentile(latencies, 50), 1),
            "p95": round(percentile(latencies, 95), 1),
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        },
        "escalation_rate": round(escalations / len(rows), 4) if rows else 0.0,
        "gate": gate,
    }
