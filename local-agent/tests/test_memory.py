import numpy as np

from localagent.memory import identity
from localagent.memory.store import Store


def test_memory_crud_and_search(tmp_path):
    s = Store(tmp_path / "t.db")
    a = s.add_memory("Prefers window seats", "preference", [1, 0, 0], "m")
    b = s.add_memory("Lives in Austin", "place", [0, 1, 0], "m")
    hits = s.search_memories([0.9, 0.1, 0], "m", k=2)
    assert [h.id for h in hits] == [a, b]
    assert hits[0].score > hits[1].score
    assert s.search_memories([1, 0, 0], "other-model") == []
    s.update_memory(a, text="Prefers aisle seats")
    assert s.get_memory(a).text == "Prefers aisle seats"
    assert s.delete_memory(a)
    assert s.get_memory(a) is None
    assert [m.id for m in s.search_memories([1, 0, 0], "m", k=5)] == [b]


def test_identity_reflects_forget(tmp_path):
    s = Store(tmp_path / "t.db")
    mid = s.add_memory("Is vegetarian", "fact", None, None)
    path = tmp_path / "identity" / "about-me.md"
    assert "Is vegetarian" in identity.write(s, path, "Ari")
    s.delete_memory(mid)
    text = identity.write(s, path, "Ari")
    assert "Is vegetarian" not in text and "Nothing remembered yet" in text
    assert path.read_text() == text


def test_think_filter_across_chunks():
    from localagent.llm.ollama import ThinkFilter, strip_think
    f = ThinkFilter()
    out = "".join(f.feed(p) for p in ["Hel", "lo <thi", "nk>secret", " stuff</th", "ink>world", "!"])
    assert out == "Hello world!"
    assert strip_think("<think>x</think> answer") == "answer"
