"""Fast decision backend: an embedding prototype (k-nearest-neighbour) classifier.

For each question, every labelled example is embedded once. A new message is
embedded (one ~10-30 ms call to a small embedding model) and each label is
scored by the mean cosine similarity of its top-k closest examples. A
temperature-scaled softmax turns scores into probabilities.

It answers every question in one embedding pass with no text generation,
which is the same contract as a Jev-style System-One model. It also learns
immediately: a user correction is just a new labelled example.
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Awaitable, Callable

import numpy as np

from ..memory.store import Store, normalize
from .types import Answer, Question, answer_from_probs

Embedder = Callable[[list[str]], Awaitable[list[list[float]]]]

SEED_FILE = "seed_examples.jsonl"

# Maps a column in the seed file to (question name, label formatter).
SEED_COLUMNS = {
    "intent": ("intent", str),
    "memory": ("needs_memory_write", lambda v: "yes" if v else "no"),
    "complexity": ("complexity", lambda v: str(int(v))),
}


def load_jsonl(name: str) -> list[dict]:
    text = resources.files("localagent.data").joinpath(name).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def seed_store(store: Store) -> int:
    """Insert the shipped seed examples once. Returns the number inserted."""
    if store.count_examples("seed"):
        return 0
    n = 0
    for row in load_jsonl(SEED_FILE):
        for column, (question, fmt) in SEED_COLUMNS.items():
            if column in row:
                store.add_example(question, fmt(row[column]), row["text"], source="seed")
                n += 1
    return n


class PrototypeClassifier:
    name = "prototype"

    def __init__(self, store: Store, embed: Embedder, embed_model: str,
                 temperature: float = 30.0, top_k: int = 3):
        self.store = store
        self.embed = embed
        self.embed_model = embed_model
        self.temperature = temperature
        self.top_k = top_k
        self._cache: dict[str, tuple[list[str], np.ndarray]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    async def ensure_embeddings(self, batch: int = 64) -> int:
        missing = self.store.examples_missing_embedding(self.embed_model)
        for i in range(0, len(missing), batch):
            chunk = missing[i:i + batch]
            vecs = await self.embed([r["text"] for r in chunk])
            for row, vec in zip(chunk, vecs):
                self.store.set_example_embedding(row["id"], vec, self.embed_model)
        if missing:
            self.invalidate()
        return len(missing)

    def _matrix(self, question: str) -> tuple[list[str], np.ndarray] | None:
        if question not in self._cache:
            rows = self.store.examples_for(question, self.embed_model)
            if not rows:
                return None
            labels = [label for label, _ in rows]
            mat = normalize(np.stack([vec for _, vec in rows]).astype(np.float32))
            self._cache[question] = (labels, mat)
        return self._cache[question]

    def classify_vec(self, q: Question, vec: np.ndarray) -> Answer | None:
        data = self._matrix(q.name)
        if data is None:
            return None
        labels, mat = data
        sims = mat @ vec
        scores: dict[str, float] = {}
        for label in q.labels:
            idx = [i for i, l in enumerate(labels) if l == label]
            if not idx:
                continue
            top = np.sort(sims[idx])[-self.top_k:]
            scores[label] = float(top.mean())
        if not scores:
            return None
        keys = list(scores)
        logits = np.array([scores[k] for k in keys]) * self.temperature
        logits -= logits.max()
        exp = np.exp(logits)
        probs = dict(zip(keys, (exp / exp.sum()).tolist()))
        return answer_from_probs(q, probs)

    async def decide(self, text: str, questions: list[Question]) -> dict[str, Answer]:
        await self.ensure_embeddings()
        vec = np.asarray((await self.embed([text]))[0], dtype=np.float32)
        norm = np.linalg.norm(vec) or 1.0
        vec = vec / norm
        out: dict[str, Answer] = {}
        for q in questions:
            ans = self.classify_vec(q, vec)
            if ans is not None:
                out[q.name] = ans
        return out
