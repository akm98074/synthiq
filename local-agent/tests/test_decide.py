import json

import pytest

from localagent.decide.questions import INTENT, NEEDS_MEMORY_WRITE, STANDARD
from localagent.decide.systemone import build_request, parse_response
from localagent.decide.types import answer_from_probs


def test_answer_normalises_probs():
    a = answer_from_probs(INTENT, {"task": 2.0, "schedule": 2.0, "chit_chat": 4.0})
    assert a.label == "chit_chat"
    assert abs(sum(a.probs.values()) - 1) < 1e-9
    assert a.confidence == pytest.approx(0.5)


async def test_seed_examples_loaded_and_embedded(runtime):
    assert runtime.store.count_examples("seed") > 300  # 3 questions x ~144 rows
    n = await runtime.prototype.ensure_embeddings()
    assert n == runtime.store.count_examples("seed")
    assert await runtime.prototype.ensure_embeddings() == 0  # cached


@pytest.mark.parametrize("text,intent", [
    ("remind me to call the dentist at 5pm", "schedule"),
    ("what do you know about me?", "memory_query"),
    ("I'm allergic to cats", "memory_write"),
])
async def test_prototype_classifies(runtime, text, intent):
    answers = await runtime.prototype.decide(text, STANDARD)
    assert answers["intent"].label == intent
    assert set(answers) == {"intent", "needs_memory_write", "complexity"}


async def test_hybrid_escalates_on_low_confidence(runtime):
    runtime.router.threshold = 0.999  # force escalation
    d = await runtime.router.decide("hello there friend")
    assert d.escalated and d.backend == "prototype+slm"
    assert d.id is not None
    runtime.router.threshold = 0.0
    d2 = await runtime.router.decide("hello there friend")
    assert not d2.escalated and d2.backend == "prototype"


async def test_slm_backend(runtime):
    d = await runtime.router.decide("remind me to stretch", backend="slm", log_it=False)
    assert d.backend == "slm"
    assert d["intent"].label == "schedule"
    assert d["intent"].confidence >= 0.8


async def test_systemone_falls_back_when_unreachable(runtime):
    runtime.systemone.base_url = "http://127.0.0.1:9"
    d = await runtime.router.decide("remind me at noon", backend="systemone", log_it=False)
    assert any("systemone failed" in n for n in d.notes)
    assert d["intent"].label == "schedule"


async def test_correction_becomes_example(runtime):
    d = await runtime.router.decide("ship it")
    before = runtime.store.count_examples("user")
    await runtime.router.correct(d.id, "intent", "computer_action")
    assert runtime.store.count_examples("user") == before + 1
    assert runtime.store.get_decision(d.id)["corrections"] == {"intent": "computer_action"}
    with pytest.raises(ValueError):
        await runtime.router.correct(d.id, "intent", "nope")


def test_systemone_wire_parsing():
    req = build_request("hi", STANDARD)
    assert req["questions"][0]["choices"]["task"]
    data = {"answers": [
        {"name": "intent", "probabilities": {"task": 0.7, "chit_chat": 0.3}},
        {"name": "needs_memory_write", "probability": 0.2},
    ]}
    out = parse_response(data, STANDARD)
    assert out["intent"].label == "task"
    assert out["needs_memory_write"].label == "no"
    out2 = parse_response({"needs_memory_write": {"probs": {"true": 0.9, "false": 0.1}}}, [NEEDS_MEMORY_WRITE])
    assert out2["needs_memory_write"].yes
