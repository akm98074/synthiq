"""Web search: the first step for anything that changes (prices, shops, opening hours, news).

Uses DuckDuckGo's plain-HTML results page (no account, no API key, no JavaScript). Only
the query leaves the Mac; results come back as titles, links and snippets, which are
untrusted and fenced like any web page. The agent then opens the best result with
`browser_open` (for a shop, its own site and search box) to read the actual answer.
"""
from __future__ import annotations

import html
import re
from typing import Awaitable, Callable
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from ..tools.base import Tool, ToolError, ToolResult, i, obj, s

ENDPOINT = "https://html.duckduckgo.com/html/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Version/17.0 Safari/605.1.15")
RESULT = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?P<rest>.*?)(?=<a[^>]*class="[^"]*result__a|\Z)', re.S)
SNIPPET = re.compile(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div|td)>', re.S)
TAG = re.compile(r"<[^>]+>")

Fetch = Callable[[str], Awaitable[str]]


def _clean(text: str) -> str:
    return " ".join(html.unescape(TAG.sub("", text)).split())


def _real_url(href: str) -> str:
    """DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<url>; unwrap them."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parts = urlparse(href)
    if parts.netloc.endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg", [""])[0]
        if target:
            return target
    return href


def parse_results(page: str, limit: int = 8) -> list[dict]:
    out, seen = [], set()
    for m in RESULT.finditer(page):
        url = _real_url(m.group("href"))
        host = urlparse(url).netloc
        if not url.startswith("http") or "duckduckgo.com" in host or url in seen:
            continue   # ads and internal links
        seen.add(url)
        snip = SNIPPET.search(m.group("rest"))
        out.append({"title": _clean(m.group("title")), "url": url, "site": host.removeprefix("www."),
                    "snippet": _clean(snip.group(1)) if snip else ""})
        if len(out) >= limit:
            break
    return out


async def ddg_fetch(query: str) -> str:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": UA}, follow_redirects=True) as c:
        r = await c.post(ENDPOINT, data={"q": query, "kl": "us-en"})
        r.raise_for_status()
        return r.text


def web_tools(fetch: Fetch = ddg_fetch) -> list[Tool]:
    async def search(a: dict) -> ToolResult:
        query = a["query"].strip()
        if not query:
            raise ToolError("Say what to search for.")
        if a.get("site"):
            site = urlparse(a["site"] if "://" in a["site"] else "https://" + a["site"]).netloc or a["site"]
            query += f" site:{site.removeprefix('www.')}"
        try:
            page = await fetch(query)
        except httpx.HTTPError as exc:
            raise ToolError(f"Web search failed ({exc.__class__.__name__}). Try browser_open with "
                            f"https://www.bing.com/search?q={quote_plus(query)}") from exc
        results = parse_results(page, a.get("limit", 6))
        if not results:
            if "anomaly" in page.lower() or "captcha" in page.lower():
                raise ToolError("The search engine asked for a robot check. Use browser_open with "
                                f"https://www.bing.com/search?q={quote_plus(query)} instead.")
            return ToolResult(f"No web results for “{query}”.", "No results", [])
        lines = [f"{n}. {r['title']} — {r['site']}\n   {r['url']}\n   {r['snippet']}"
                 for n, r in enumerate(results, 1)]
        return ToolResult(f"Web results for “{query}”:\n" + "\n".join(lines),
                          f"Searched the web: {len(results)} result(s)",
                          [{"title": r["title"], "url": r["url"], "site": r["site"]} for r in results], untrusted=True)

    return [Tool(
        "web_search",
        "Search the web. Use it first for anything that changes or is local: prices, shops, restaurants, "
        "opening hours, phone numbers, weather, news. Then open the best result with browser_open.",
        obj({"query": s("What to search for, including the place, e.g. 'Chutneys Bellevue WA'"),
             "site": s("Optional: only this website, e.g. safeway.com"),
             "limit": i("Max results (default 6)")}, ["query"]),
        "read", "web", search, lambda a: f"Search the web for “{a.get('query', '')}”",
        ("task", "computer_action", "quick_answer", "schedule"))]
