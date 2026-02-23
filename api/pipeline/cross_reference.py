"""
Stage 3 — Cross-reference analysis.

Two analyses:
1. contradiction_detection  — Claude Haiku compares claims about the same entity
                              across different sources and flags conflicts.
2. gap_detection            — entity present in ≥60 % of sources but absent in ≥1.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_GAP_THRESHOLD = 0.60  # entity must appear in at least this fraction of sources


# ─── Contradiction detection ──────────────────────────────────────────────────


_CONTRADICTION_PROMPT = """\
You are a research analyst. The following excerpts from different sources all \
mention the entity "{entity}". Identify any factual contradictions or \
significant conflicts between the claims made about this entity.

Sources:
{source_blocks}

Respond with a JSON array of contradiction objects. Each object must have:
  "claim"        – a short (≤15 words) description of the conflict
  "source_a_idx" – 0-based index of first conflicting source
  "source_b_idx" – 0-based index of second conflicting source
  "quote_a"      – verbatim or near-verbatim quote from source_a (≤60 words)
  "quote_b"      – verbatim or near-verbatim quote from source_b (≤60 words)
  "significance" – float 0.0–1.0 (1.0 = direct factual contradiction)

If there are no contradictions, respond with an empty array: []
Respond with valid JSON only — no markdown fences."""


async def detect_contradictions(
    client: Any,
    entity_graph: dict[str, Any],
    source_id_map: dict[str, str],  # source_id → display name (filename or url)
) -> list[dict[str, Any]]:
    """
    For each cross-source entity in entity_graph, ask Claude Haiku to identify
    contradictions. Returns a list of contradiction dicts.
    """
    from config import settings  # local import to respect monkeypatch in tests

    if not settings.anthropic_api_key:
        logger.warning("No Anthropic key — skipping contradiction detection")
        return []

    contradictions: list[dict[str, Any]] = []

    for entity_name, entity_data in entity_graph.items():
        source_ids = entity_data.get("source_ids", [])
        if len(source_ids) < 2:
            continue  # need ≥2 sources to compare

        # Collect representative quotes per source
        snippets: list[dict[str, str]] = entity_data.get("snippets", [])
        if not snippets:
            continue

        # Group snippets by source_id
        by_source: dict[str, list[str]] = {}
        for snip in snippets:
            sid = snip.get("source_id", "")
            if sid:
                by_source.setdefault(sid, []).append(snip.get("text", ""))

        ordered_sources = [s for s in source_ids if s in by_source]
        if len(ordered_sources) < 2:
            continue

        source_blocks = "\n\n".join(
            f"[{i}] {source_id_map.get(sid, sid)}:\n"
            + " | ".join(by_source[sid][:3])  # up to 3 snippets
            for i, sid in enumerate(ordered_sources)
        )

        prompt = _CONTRADICTION_PROMPT.format(
            entity=entity_name,
            source_blocks=source_blocks,
        )

        try:
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                try:
                    a_idx = int(item["source_a_idx"])
                    b_idx = int(item["source_b_idx"])
                    if a_idx >= len(ordered_sources) or b_idx >= len(ordered_sources):
                        continue
                    contradictions.append(
                        {
                            "id": str(uuid.uuid4()),
                            "entity": entity_name,
                            "claim": str(item.get("claim", "")),
                            "source_a_id": ordered_sources[a_idx],
                            "source_a": source_id_map.get(ordered_sources[a_idx], ordered_sources[a_idx]),
                            "source_b_id": ordered_sources[b_idx],
                            "source_b": source_id_map.get(ordered_sources[b_idx], ordered_sources[b_idx]),
                            "quote_a": str(item.get("quote_a", "")),
                            "quote_b": str(item.get("quote_b", "")),
                            "significance": float(item.get("significance", 0.5)),
                        }
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Contradiction detection failed for entity %r: %s", entity_name, exc)

    # Sort by significance descending
    contradictions.sort(key=lambda c: c["significance"], reverse=True)
    return contradictions


# ─── Gap detection ────────────────────────────────────────────────────────────


def detect_gaps(
    entity_graph: dict[str, Any],
    all_source_ids: list[str],
) -> list[dict[str, Any]]:
    """
    An entity is a "gap" if it appears in ≥ 60 % of sources but is absent
    from at least one source.  Returns list of gap dicts sorted by
    mentioned_in_count descending.
    """
    n_sources = len(all_source_ids)
    if n_sources < 2:
        return []

    all_source_set = set(all_source_ids)
    gaps: list[dict[str, Any]] = []

    for entity_name, entity_data in entity_graph.items():
        present_ids = set(entity_data.get("source_ids", []))
        mentioned_count = len(present_ids & all_source_set)
        fraction = mentioned_count / n_sources

        if fraction >= _GAP_THRESHOLD and mentioned_count < n_sources:
            missing_ids = list(all_source_set - present_ids)
            gaps.append(
                {
                    "topic": entity_name,
                    "mentioned_in_count": mentioned_count,
                    "missing_in_count": len(missing_ids),
                    "missing_source_ids": missing_ids,
                }
            )

    gaps.sort(key=lambda g: g["mentioned_in_count"], reverse=True)
    return gaps
