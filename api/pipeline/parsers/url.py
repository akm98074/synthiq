"""
URL parser using httpx + BeautifulSoup.

Fetches a URL, strips boilerplate (nav, footer, scripts, ads) via CSS
selector pruning, and returns clean article text.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from .base import PageText

_BOILERPLATE_TAGS = [
    "script", "style", "noscript",
    "nav", "footer", "header", "aside",
    "form", "button", "svg", "img",
    "iframe", "ads", "advertisement",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Synthiq/1.0; +https://synthiq.app)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def parse_url(url: str) -> list[PageText]:
    """
    Fetch and parse a URL. Returns a single PageText with the clean body text.

    Raises httpx.HTTPStatusError on 4xx/5xx responses.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30.0,
        headers=_HEADERS,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        html = response.text

    soup = BeautifulSoup(html, "lxml")

    # Remove boilerplate elements
    for tag in soup(_BOILERPLATE_TAGS):
        tag.decompose()

    # Try to focus on main content area
    main_content = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find(class_=re.compile(r"content|article|post|entry", re.I))
        or soup.find("body")
        or soup
    )

    raw = (main_content or soup).get_text(separator="\n", strip=True)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", raw).strip()

    if not text:
        return []

    return [PageText(page_number=1, text=text)]
