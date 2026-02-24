"""
Stage 4: Generate structured outline from source map using Claude Sonnet 4.6.

Given the entity graph, source map, and deliverable type, Claude creates a
hierarchical outline with sections, subsections, assigned chunk IDs, source
attribution, and suggested word lengths.
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

_DELIVERABLE_DESCRIPTIONS: dict[str, str] = {
    "executive_memo": "a concise executive memo for leadership decision-making",
    "competitive_landscape": "a comprehensive competitive landscape analysis",
    "investment_thesis": "a structured investment thesis with market, team, and financial analysis",
    "project_brief": "a project brief covering objectives, scope, timeline, and risks",
    "literature_summary": "a literature summary synthesising key findings and themes",
}

_TOTAL_WORDS_BY_TYPE: dict[str, int] = {
    "executive_memo": 700,
    "competitive_landscape": 2000,
    "investment_thesis": 1600,
    "project_brief": 1000,
    "literature_summary": 1400,
}

_OUTLINE_PROMPT = """\
You are a research analyst creating a structured outline for {deliverable_desc}.

## Source Map Summary
Clusters: {cluster_summary}
Key contradictions: {contradiction_summary}
Research gaps: {gap_summary}

## Available Evidence (sample)
{evidence_summary}

## Instructions
Generate a structured outline as JSON. Be thorough and use the evidence provided.
Return ONLY valid JSON in this exact format:
{{
  "title": "<overall deliverable title>",
  "sections": [
    {{
      "id": "s1",
      "title": "<section title>",
      "description": "<1-2 sentence description>",
      "suggested_length": <word count as integer>,
      "chunk_ids": ["<chunk_id>"],
      "source_ids": ["<source_id>"],
      "subsections": [
        {{
          "id": "s1_1",
          "title": "<subsection title>",
          "description": "<brief description>",
          "suggested_length": <word count>,
          "chunk_ids": [],
          "source_ids": []
        }}
      ]
    }}
  ]
}}

Requirements:
- Include 3-6 top-level sections appropriate for {deliverable_type}
- Each section may have 0-3 subsections
- Assign chunk_ids from the evidence to the most relevant sections
- suggested_length values should total approximately {total_words} words
- Ensure key clusters, contradictions, and gaps are addressed
"""

_FALLBACK_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "s1",
        "title": "Executive Summary",
        "description": "Overview of key findings and recommendations.",
        "suggested_length": 200,
        "chunk_ids": [],
        "source_ids": [],
        "subsections": [],
    },
    {
        "id": "s2",
        "title": "Key Findings",
        "description": "Main insights extracted from the research.",
        "suggested_length": 400,
        "chunk_ids": [],
        "source_ids": [],
        "subsections": [],
    },
    {
        "id": "s3",
        "title": "Analysis",
        "description": "Detailed analysis of the evidence.",
        "suggested_length": 500,
        "chunk_ids": [],
        "source_ids": [],
        "subsections": [],
    },
    {
        "id": "s4",
        "title": "Conclusions and Recommendations",
        "description": "Actionable conclusions based on the research.",
        "suggested_length": 300,
        "chunk_ids": [],
        "source_ids": [],
        "subsections": [],
    },
]


async def generate_outline(
    client: Any,
    deliverable_type: str,
    source_map: dict[str, Any],
    entity_graph: dict[str, Any],
    chunk_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Generate a structured deliverable outline using Claude Sonnet 4.6.

    Returns outline dict; falls back to a default outline on any error.
    """
    if not client:
        log.warning("No Anthropic client — returning fallback outline")
        return _build_fallback(chunk_rows)

    deliverable_desc = _DELIVERABLE_DESCRIPTIONS.get(
        deliverable_type, "a research synthesis document"
    )
    total_words = _TOTAL_WORDS_BY_TYPE.get(deliverable_type, 1200)

    cluster_summary = _summarise_clusters(source_map)
    contradiction_summary = _summarise_contradictions(source_map)
    gap_summary = _summarise_gaps(source_map)
    evidence_summary = _summarise_evidence(chunk_rows)

    prompt = _OUTLINE_PROMPT.format(
        deliverable_desc=deliverable_desc,
        deliverable_type=deliverable_type,
        cluster_summary=cluster_summary,
        contradiction_summary=contradiction_summary,
        gap_summary=gap_summary,
        evidence_summary=evidence_summary,
        total_words=total_words,
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        outline = json.loads(raw)

        if "sections" not in outline or not isinstance(outline["sections"], list):
            raise ValueError("Missing 'sections' list in outline response")

        # Ensure required fields exist on every section
        for section in outline["sections"]:
            section.setdefault("chunk_ids", [])
            section.setdefault("source_ids", [])
            section.setdefault("subsections", [])

        return outline

    except Exception as exc:
        log.warning("Outline generation failed (%s) — using fallback", exc)
        return _build_fallback(chunk_rows)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _summarise_clusters(source_map: dict[str, Any]) -> str:
    clusters = source_map.get("clusters") or []
    if not clusters:
        return "No clusters available"
    parts = [
        f"{c.get('label', 'Cluster')} ({c.get('chunk_count', 0)} chunks)"
        for c in clusters[:6]
    ]
    return "; ".join(parts)


def _summarise_contradictions(source_map: dict[str, Any]) -> str:
    contradictions = source_map.get("contradictions") or []
    if not contradictions:
        return "None detected"
    parts = [
        f"{c.get('entity', '')}: {c.get('source_a', '')} vs {c.get('source_b', '')}"
        for c in contradictions[:3]
    ]
    return "; ".join(parts)


def _summarise_gaps(source_map: dict[str, Any]) -> str:
    gaps = source_map.get("gaps") or []
    if not gaps:
        return "None detected"
    return "; ".join(g.get("topic", "") for g in gaps[:3])


def _summarise_evidence(chunk_rows: list[dict[str, Any]]) -> str:
    lines = []
    for row in chunk_rows[:40]:
        snippet = (row.get("content") or "")[:150].replace("\n", " ")
        lines.append(
            f"- chunk_id={row['id']} source_id={row['source_id']}: {snippet}…"
        )
    return "\n".join(lines) or "No chunks available"


def _build_fallback(chunk_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribute chunk IDs across the default fallback outline."""
    sections = copy.deepcopy(_FALLBACK_SECTIONS)
    chunk_ids = [r["id"] for r in chunk_rows]

    # Skip first section (executive summary) — distribute to the rest
    distributable = sections[1:]
    if chunk_ids and distributable:
        per_section = max(1, len(chunk_ids) // len(distributable))
        for i, section in enumerate(distributable):
            assigned = chunk_ids[i * per_section : (i + 1) * per_section]
            section["chunk_ids"] = assigned
            section["source_ids"] = list(
                {r["source_id"] for r in chunk_rows if r["id"] in assigned}
            )

    return {
        "title": "Research Synthesis",
        "sections": sections,
    }
