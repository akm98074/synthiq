import asyncio

import httpx
import pytest

from localagent.connectors.websearch import parse_results, web_tools
from localagent.tools.base import ToolError
from test_actions import chat

PAGE = """
<div class="result results_links result--ad"><a rel="nofollow" class="result__a"
  href="https://duckduckgo.com/y.js?ad_provider=x">Ad: Cheap onions</a></div>
<div class="result results_links"><h2 class="result__title"><a rel="nofollow" class="result__a"
  href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.safeway.com%2Fshop%2Fproduct-details.184060081.html&amp;rut=abc">
  Yellow Onions - <b>Safeway</b></a></h2>
  <a class="result__snippet" href="#">Yellow onions $1.49/lb at Safeway Sammamish &amp; nearby stores.</a></div>
<div class="result results_links"><h2 class="result__title"><a rel="nofollow" class="result__a"
  href="https://www.chutneysbellevue.com/">Chutneys Bistro | Indian restaurant in Bellevue</a></h2>
  <a class="result__snippet" href="#">1015 108th Ave NE, Bellevue. Open 11am-10pm. 4.4 stars.</a></div>
<div class="result results_links"><a class="result__a" href="https://www.chutneysbellevue.com/">dup</a></div>
"""


def test_parse_results_unwraps_and_skips_ads():
    res = parse_results(PAGE)
    assert [r["site"] for r in res] == ["safeway.com", "chutneysbellevue.com"]
    assert res[0]["url"] == "https://www.safeway.com/shop/product-details.184060081.html"
    assert res[0]["title"] == "Yellow Onions - Safeway"
    assert res[0]["snippet"].startswith("Yellow onions $1.49/lb") and "&amp;" not in res[0]["snippet"]


def test_web_search_tool():
    seen = []

    async def fetch(q):
        seen.append(q)
        return PAGE

    tool = web_tools(fetch)[0]
    assert tool.tier == "read" and "quick_answer" in tool.intents
    res = asyncio.run(tool.run({"query": "onion price Sammamish", "site": "https://www.safeway.com/"}))
    assert seen == ["onion price Sammamish site:safeway.com"]
    assert res.untrusted and "1. Yellow Onions - Safeway — safeway.com" in res.content

    async def blocked(q):
        return "<html>Unfortunately, bots use DuckDuckGo too. anomaly detected</html>"

    with pytest.raises(ToolError, match="bing.com/search"):
        asyncio.run(web_tools(blocked)[0].run({"query": "x"}))

    async def down(q):
        raise httpx.ConnectError("offline")

    with pytest.raises(ToolError, match="Web search failed"):
        asyncio.run(web_tools(down)[0].run({"query": "x"}))


@pytest.fixture
def search_client(fake_ollama, home, files_home, fake_runner):
    from fastapi.testclient import TestClient

    from conftest import FakeBrowser
    from localagent.config import Settings, save_settings
    from localagent.server import create_app

    queries = []

    async def fetch(q):
        queries.append(q)
        return PAGE

    s = Settings(ollama_url=fake_ollama.url, confidence_threshold=1.0, enable_messages=False,
                 file_roots=str(files_home / "Downloads"))
    save_settings(s, home)
    with TestClient(create_app(s, home, runner=fake_runner, scheduler=False, browser=FakeBrowser(),
                               web_fetch=fetch)) as c:
        c.queries = queries
        yield c


def test_local_lookups_search_first(search_client):
    c = search_client
    ev = chat(c, "find price of onion in safeway sammamish")
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["tool"] == "web_search" and res["ok"]
    assert c.queries[-1] == "onion price Safeway Sammamish site:safeway.com"
    ev = chat(c, "chutneys bellevue")
    assert next(e for e in ev if e["type"] == "decision")["decision"]["answers"]["intent"]["label"] == "quick_answer"
    res = next(e for e in ev if e["type"] == "tool_result")
    assert res["tool"] == "web_search" and c.queries[-1] == "Chutneys Bellevue WA"
    conns = {x["id"]: x for x in c.get("/api/connectors").json()}
    assert conns["web"]["active"] and conns["web"]["tools"] == [{"name": "web_search", "tier": "read"}]


def test_web_seeds_added_on_upgrade(tmp_path):
    from localagent.decide.prototype import seed_store
    from localagent.memory.store import Store

    store = Store(tmp_path / "x.db")
    store.add_example("intent", "chit_chat", "hello", source="seed")       # an older install
    store.add_example("should_nudge", "yes", "reply to boss", source="seed")
    added = seed_store(store)
    assert added and store.meta_get("seeded:web_seed.jsonl") == "1"
    texts = [t for t, in store.query("SELECT text FROM examples WHERE source='seed'")]
    assert "chutneys bellevue" in texts and texts.count("hey there") == 0   # legacy sets not re-added
    assert seed_store(store) == 0
