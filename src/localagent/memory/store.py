"""SQLite persistence: messages, memories, decisions and labelled examples.

Vectors are stored as float32 blobs and searched with numpy, which is fast
enough for personal-scale data (tens of thousands of rows) and needs no native
SQLite extensions.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  decision_id INTEGER,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'fact',
  embedding BLOB,
  embed_model TEXT,
  source_message_id INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  payload TEXT NOT NULL,
  backend TEXT NOT NULL,
  latency_ms REAL NOT NULL,
  escalated INTEGER NOT NULL DEFAULT 0,
  corrections TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  label TEXT NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'seed',
  embedding BLOB,
  embed_model TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_examples_q ON examples(question);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

MEMORY_KINDS = ("preference", "fact", "person", "place", "routine")


def to_blob(vec: list[float] | np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes | None) -> np.ndarray | None:
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


def normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


@dataclass
class Memory:
    id: int
    text: str
    kind: str
    created_at: float
    updated_at: float
    score: float | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if d["score"] is None:
            d.pop("score")
        else:
            d["score"] = round(d["score"], 4)
        return d


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._exec(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._query(sql, params)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, params).fetchall()

    # ── small key/value state ─────────────────────────────────────────────
    def meta_get(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    def meta_set(self, key: str, value: str) -> None:
        self._exec("INSERT INTO meta(key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def user_messages_since(self, ts: float, limit: int = 60) -> list[str]:
        rows = self._query("SELECT content FROM messages WHERE role='user' AND created_at > ? "
                           "ORDER BY id DESC LIMIT ?", (ts, limit))
        return [r["content"] for r in reversed(rows)]

    def memory_vectors(self, embed_model: str) -> list[tuple[int, str, np.ndarray]]:
        rows = self._query("SELECT id, text, embedding FROM memories WHERE embedding IS NOT NULL "
                           "AND embed_model=? ORDER BY id", (embed_model,))
        return [(r["id"], r["text"], from_blob(r["embedding"])) for r in rows]

    # ── messages ──────────────────────────────────────────────────────────
    def add_message(self, role: str, content: str, decision_id: int | None = None) -> int:
        cur = self._exec(
            "INSERT INTO messages(role, content, decision_id, created_at) VALUES (?,?,?,?)",
            (role, content, decision_id, time.time()),
        )
        return int(cur.lastrowid)

    def set_message_decision(self, message_id: int, decision_id: int | None) -> None:
        self._exec("UPDATE messages SET decision_id=? WHERE id=?", (decision_id, message_id))

    def recent_messages(self, limit: int = 50) -> list[dict]:
        rows = self._query(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in reversed(rows)]

    def clear_messages(self) -> None:
        self._exec("DELETE FROM messages")

    # ── decisions ─────────────────────────────────────────────────────────
    def log_decision(self, decision_dict: dict) -> int:
        cur = self._exec(
            "INSERT INTO decisions(text, payload, backend, latency_ms, escalated, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                decision_dict["text"],
                json.dumps(decision_dict),
                decision_dict["backend"],
                decision_dict["latency_ms"],
                int(decision_dict["escalated"]),
                time.time(),
            ),
        )
        return int(cur.lastrowid)

    def get_decision(self, decision_id: int) -> dict | None:
        rows = self._query("SELECT * FROM decisions WHERE id=?", (decision_id,))
        return self._decision_row(rows[0]) if rows else None

    def list_decisions(self, limit: int = 100) -> list[dict]:
        rows = self._query("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))
        return [self._decision_row(r) for r in rows]

    def add_correction(self, decision_id: int, question: str, label: str) -> None:
        row = self.get_decision(decision_id)
        if row is None:
            raise KeyError(decision_id)
        corrections = row["corrections"]
        corrections[question] = label
        self._exec(
            "UPDATE decisions SET corrections=? WHERE id=?",
            (json.dumps(corrections), decision_id),
        )

    @staticmethod
    def _decision_row(r: sqlite3.Row) -> dict:
        payload = json.loads(r["payload"])
        payload["id"] = r["id"]
        payload["created_at"] = r["created_at"]
        payload["corrections"] = json.loads(r["corrections"]) if r["corrections"] else {}
        return payload

    # ── labelled examples (decision layer training data) ─────────────────
    def count_examples(self, source: str | None = None) -> int:
        if source:
            return self._query("SELECT COUNT(*) c FROM examples WHERE source=?", (source,))[0]["c"]
        return self._query("SELECT COUNT(*) c FROM examples")[0]["c"]

    def count_examples_for(self, question: str, source: str) -> int:
        return self._query("SELECT COUNT(*) c FROM examples WHERE question=? AND source=?",
                           (question, source))[0]["c"]

    def add_example(
        self,
        question: str,
        label: str,
        text: str,
        source: str = "user",
        embedding: list[float] | None = None,
        embed_model: str | None = None,
    ) -> int:
        cur = self._exec(
            "INSERT INTO examples(question, label, text, source, embedding, embed_model, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                question,
                label,
                text,
                source,
                to_blob(embedding) if embedding is not None else None,
                embed_model,
                time.time(),
            ),
        )
        return int(cur.lastrowid)

    def examples_missing_embedding(self, embed_model: str) -> list[dict]:
        rows = self._query(
            "SELECT id, text FROM examples WHERE embedding IS NULL OR embed_model IS NOT ?",
            (embed_model,),
        )
        return [dict(r) for r in rows]

    def set_example_embedding(self, example_id: int, embedding: list[float], embed_model: str) -> None:
        self._exec(
            "UPDATE examples SET embedding=?, embed_model=? WHERE id=?",
            (to_blob(embedding), embed_model, example_id),
        )

    def examples_for(self, question: str, embed_model: str) -> list[tuple[str, np.ndarray]]:
        rows = self._query(
            "SELECT label, embedding FROM examples WHERE question=? AND embed_model=?",
            (question, embed_model),
        )
        return [(r["label"], from_blob(r["embedding"])) for r in rows if r["embedding"]]

    # ── memories ──────────────────────────────────────────────────────────
    def add_memory(
        self,
        text: str,
        kind: str,
        embedding: list[float] | None,
        embed_model: str | None,
        source_message_id: int | None = None,
    ) -> int:
        now = time.time()
        cur = self._exec(
            "INSERT INTO memories(text, kind, embedding, embed_model, source_message_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                text,
                kind if kind in MEMORY_KINDS else "fact",
                to_blob(embedding) if embedding is not None else None,
                embed_model,
                source_message_id,
                now,
                now,
            ),
        )
        return int(cur.lastrowid)

    def update_memory(
        self,
        memory_id: int,
        text: str | None = None,
        kind: str | None = None,
        embedding: list[float] | None = None,
        embed_model: str | None = None,
    ) -> bool:
        current = self.get_memory(memory_id)
        if current is None:
            return False
        self._exec(
            "UPDATE memories SET text=?, kind=?, embedding=COALESCE(?, embedding),"
            " embed_model=COALESCE(?, embed_model), updated_at=? WHERE id=?",
            (
                text if text is not None else current.text,
                kind if kind in MEMORY_KINDS else current.kind,
                to_blob(embedding) if embedding is not None else None,
                embed_model,
                time.time(),
                memory_id,
            ),
        )
        return True

    def delete_memory(self, memory_id: int) -> bool:
        """Hard delete: the row and its embedding are removed together."""
        cur = self._exec("DELETE FROM memories WHERE id=?", (memory_id,))
        return cur.rowcount > 0

    def get_memory(self, memory_id: int) -> Memory | None:
        rows = self._query(
            "SELECT id, text, kind, created_at, updated_at FROM memories WHERE id=?", (memory_id,)
        )
        return Memory(**dict(rows[0])) if rows else None

    def list_memories(self) -> list[Memory]:
        rows = self._query(
            "SELECT id, text, kind, created_at, updated_at FROM memories ORDER BY kind, id"
        )
        return [Memory(**dict(r)) for r in rows]

    def memories_missing_embedding(self, embed_model: str) -> list[dict]:
        rows = self._query(
            "SELECT id, text FROM memories WHERE embedding IS NULL OR embed_model IS NOT ?",
            (embed_model,),
        )
        return [dict(r) for r in rows]

    def search_memories(
        self, query_vec: list[float], embed_model: str, k: int = 5, min_score: float = 0.0
    ) -> list[Memory]:
        rows = self._query(
            "SELECT id, text, kind, created_at, updated_at, embedding FROM memories"
            " WHERE embedding IS NOT NULL AND embed_model=?",
            (embed_model,),
        )
        if not rows:
            return []
        mat = normalize(np.stack([from_blob(r["embedding"]) for r in rows]))
        q = normalize(np.asarray(query_vec, dtype=np.float32)[None, :])[0]
        sims = mat @ q
        order = np.argsort(-sims)[:k]
        out = []
        for i in order:
            if sims[i] < min_score:
                break
            r = rows[int(i)]
            out.append(
                Memory(r["id"], r["text"], r["kind"], r["created_at"], r["updated_at"], float(sims[i]))
            )
        return out
