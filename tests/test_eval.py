from localagent.evals.decision import QuestionResult, load_rows, run


def test_metrics():
    r = QuestionResult("q", ["a", "a", "b", "b"], ["a", "b", "b", "b"], [0.9, 0.6, 0.8, 0.7])
    assert r.accuracy() == 0.75
    assert 0 < r.macro_f1() < 1
    assert 0 <= r.ece() <= 1
    assert r.confusions() == [("a", "b", 1)]


async def test_eval_runs_on_shipped_set(runtime):
    rows = load_rows(None)
    assert len(rows) == 150
    report = await run(runtime.router, rows[:40], backend="prototype")
    names = {q["question"] for q in report["questions"]}
    assert names == {"intent", "needs_memory_write"}
    assert report["gate"] is not None
    assert report["latency_ms"]["p50"] >= 0
