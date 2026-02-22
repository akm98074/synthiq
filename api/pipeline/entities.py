"""
Named-entity extraction using Claude Haiku.

Sends up to BATCH_SIZE chunk texts per API call and returns a structured
dict of entities for each chunk: {people, organizations, locations,
dates, key_concepts}.

Falls back to empty entity dicts when no Anthropic API key is set (dev).
"""
from __future__ import annotations

import json
import logging
import re

import anthropic

from config import settings

log = logging.getLogger(__name__)

_ENTITY_KEYS = ["people", "organizations", "locations", "dates", "key_concepts"]

_SYSTEM_PROMPT = (
    "You are an entity extractor. Given numbered text blocks, extract named "
    "entities from each block. Respond ONLY with a valid JSON array—one "
    "object per block—with these keys: people, organizations, locations, "
    "dates, key_concepts. Each value is a list of strings. "
    "Never include markdown, code fences, or commentary."
)


async def extract_entities_batch(
    client: anthropic.AsyncAnthropic,
    texts: list[str],
) -> list[dict[str, list[str]]]:
    """
    Extract entities for a list of texts.

    Returns one entity dict per input text.
    Always returns a list of the same length as `texts`, even on error.
    """
    if not texts:
        return []

    if not settings.anthropic_api_key:
        return [_empty_entities() for _ in texts]

    batch_size = settings.entity_batch_size
    results: list[dict[str, list[str]]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_results = await _extract_batch(client, batch)
        results.extend(batch_results)

    return results


# ─── Internals ────────────────────────────────────────────────────────────────


async def _extract_batch(
    client: anthropic.AsyncAnthropic,
    texts: list[str],
) -> list[dict[str, list[str]]]:
    """Send one Claude Haiku call for a batch of texts."""
    numbered = "\n\n---\n\n".join(
        f"[{j + 1}]\n{text[:600]}" for j, text in enumerate(texts)
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": numbered}],
        )
        raw = response.content[0].text  # type: ignore[index]
        return _parse_response(raw, len(texts))
    except Exception as exc:
        log.warning("Entity extraction failed for batch of %d: %s", len(texts), exc)
        return [_empty_entities() for _ in texts]


def _parse_response(raw: str, expected: int) -> list[dict[str, list[str]]]:
    """Parse the JSON array from Claude's response, with fallback."""
    # Strip optional markdown fences
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            results = []
            for item in parsed[:expected]:
                results.append(_normalise(item))
            # Pad if the model returned fewer items than expected
            while len(results) < expected:
                results.append(_empty_entities())
            return results
    except json.JSONDecodeError:
        pass

    return [_empty_entities() for _ in range(expected)]


def _normalise(item: object) -> dict[str, list[str]]:
    if not isinstance(item, dict):
        return _empty_entities()
    return {
        key: [str(v) for v in item.get(key, [])] if isinstance(item.get(key), list) else []
        for key in _entity_keys()
    }


def _empty_entities() -> dict[str, list[str]]:
    return {k: [] for k in _entity_keys()}


def _entity_keys() -> list[str]:
    return _ENTITY_KEYS
