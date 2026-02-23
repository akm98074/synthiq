"""
Per-source confidence scoring.

score = 0.6 * domain_score + 0.4 * specificity_score

domain_score:
  pdf   → 0.90
  docx  → 0.85
  url   → 0.70
  text  → 0.65
  other → 0.60

specificity_score:
  entity density = (total named entities across chunks) / (total chunks)
  capped at 1.0 after normalisation against a reference density of 5.0
"""
from __future__ import annotations

from typing import Any

_DOMAIN_SCORES: dict[str, float] = {
    "pdf": 0.90,
    "docx": 0.85,
    "url": 0.70,
    "text": 0.65,
}
_REFERENCE_DENSITY = 5.0  # entities per chunk considered "high specificity"


def compute_confidence(
    source_type: str,
    chunks_entities: list[dict[str, Any]],
) -> float:
    """
    Return a confidence score in [0.0, 1.0] for a single source.

    Parameters
    ----------
    source_type:
        One of "pdf", "docx", "url", "text".
    chunks_entities:
        List of entity dicts as returned by pipeline.entities, one per chunk.
        Each dict has keys: people, organizations, locations, dates, key_concepts.
    """
    domain_score = _DOMAIN_SCORES.get(source_type.lower(), 0.60)

    if not chunks_entities:
        specificity_score = 0.0
    else:
        total_entities = sum(
            len(d.get("people", []))
            + len(d.get("organizations", []))
            + len(d.get("locations", []))
            + len(d.get("dates", []))
            + len(d.get("key_concepts", []))
            for d in chunks_entities
        )
        density = total_entities / len(chunks_entities)
        specificity_score = min(density / _REFERENCE_DENSITY, 1.0)

    return round(0.6 * domain_score + 0.4 * specificity_score, 4)
