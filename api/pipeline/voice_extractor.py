"""
Stage 4 — Voice Calibration: extract style signature from writing samples.

Uses Claude Sonnet 4.6 to analyse the author's writing style across up to 5
sample documents and produce:
  - A structured StyleSignature (numeric + categorical features)
  - A voice_system_prompt string injected at draft-generation time

Multiple samples are merged by averaging numeric fields and taking the most
recent categorical values (last-sample wins).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SAMPLE_CHARS = 8000  # send at most this many chars per sample to Claude

_EXTRACTION_PROMPT = """\
You are an expert writing-style analyst. Carefully read the following text \
written by an author and extract a precise style profile.

<text>
{text}
</text>

Respond ONLY with a JSON object containing exactly these keys:

{{
  "avg_sentence_length": <float: average number of words per sentence>,
  "avg_paragraph_length": <float: average number of sentences per paragraph>,
  "hedging_frequency": "<one of: low | moderate | high>",
  "technical_vocab_density": "<one of: low | moderate | high>",
  "structural_preference": "<one of: bullets | prose | mixed>",
  "section_header_style": "<one of: numbered | plain | bold | none>",
  "formality_register": "<one of: informal | neutral | formal>"
}}

Definitions:
- hedging_frequency: how often the author uses words like "possibly", \
"likely", "suggests", "may", "appears to"
- technical_vocab_density: proportion of domain-specific jargon or \
specialised terms
- structural_preference: bullets = predominantly bullet/numbered lists; \
prose = paragraphs only; mixed = both
- section_header_style: numbered = "1. Introduction"; plain = "Introduction"; \
bold = "**Introduction**"; none = no headers
- formality_register: informal = conversational, contractions; \
neutral = balanced; formal = academic or executive tone

Return valid JSON only — no markdown fences, no explanation."""


_FALLBACK_SIGNATURE: dict[str, Any] = {
    "avg_sentence_length": 20.0,
    "avg_paragraph_length": 4.0,
    "hedging_frequency": "moderate",
    "technical_vocab_density": "moderate",
    "structural_preference": "prose",
    "section_header_style": "plain",
    "formality_register": "formal",
}

_VALID_HEDGING = {"low", "moderate", "high"}
_VALID_TECH = {"low", "moderate", "high"}
_VALID_STRUCT = {"bullets", "prose", "mixed"}
_VALID_HEADER = {"numbered", "plain", "bold", "none"}
_VALID_FORMALITY = {"informal", "neutral", "formal"}


async def extract_style_signature(
    client: Any,
    text: str,
) -> dict[str, Any]:
    """
    Send up to _MAX_SAMPLE_CHARS of text to Claude Sonnet 4.6 and return a
    validated style signature dict.  Falls back to a neutral default if the
    API is unavailable or returns invalid JSON.
    """
    from config import settings

    if not settings.anthropic_api_key:
        logger.warning("No Anthropic key — returning default style signature")
        return dict(_FALLBACK_SIGNATURE)

    sample = text[:_MAX_SAMPLE_CHARS].strip()
    if not sample:
        return dict(_FALLBACK_SIGNATURE)

    prompt = _EXTRACTION_PROMPT.format(text=sample)

    try:
        response = await client.messages.create(
            model=settings.voice_analysis_model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        sig = json.loads(raw)
        return _validate_signature(sig)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Style extraction failed: %s", exc)
        return dict(_FALLBACK_SIGNATURE)


def _validate_signature(raw: dict[str, Any]) -> dict[str, Any]:
    """Clamp and coerce signature fields to valid ranges/values."""
    sig = dict(_FALLBACK_SIGNATURE)
    try:
        sig["avg_sentence_length"] = float(
            max(5.0, min(60.0, raw.get("avg_sentence_length", 20.0)))
        )
        sig["avg_paragraph_length"] = float(
            max(1.0, min(20.0, raw.get("avg_paragraph_length", 4.0)))
        )
        sig["hedging_frequency"] = (
            raw["hedging_frequency"]
            if raw.get("hedging_frequency") in _VALID_HEDGING
            else "moderate"
        )
        sig["technical_vocab_density"] = (
            raw["technical_vocab_density"]
            if raw.get("technical_vocab_density") in _VALID_TECH
            else "moderate"
        )
        sig["structural_preference"] = (
            raw["structural_preference"]
            if raw.get("structural_preference") in _VALID_STRUCT
            else "prose"
        )
        sig["section_header_style"] = (
            raw["section_header_style"]
            if raw.get("section_header_style") in _VALID_HEADER
            else "plain"
        )
        sig["formality_register"] = (
            raw["formality_register"]
            if raw.get("formality_register") in _VALID_FORMALITY
            else "formal"
        )
    except Exception as exc:
        logger.warning("Signature validation error: %s", exc)
    return sig


def merge_signatures(
    existing: dict[str, Any] | None,
    new_sig: dict[str, Any],
    existing_count: int,
) -> dict[str, Any]:
    """
    Merge a new style signature into the existing aggregate.

    Numeric fields use a running weighted average.
    Categorical fields use the most recent value (new_sig wins).
    """
    if not existing:
        return new_sig

    n = max(existing_count, 1)
    merged = dict(existing)
    # Weighted average for numeric
    for key in ("avg_sentence_length", "avg_paragraph_length"):
        old_val = float(existing.get(key, _FALLBACK_SIGNATURE[key]))
        new_val = float(new_sig.get(key, _FALLBACK_SIGNATURE[key]))
        merged[key] = round((old_val * n + new_val) / (n + 1), 2)

    # Last-sample wins for categoricals
    for key in (
        "hedging_frequency",
        "technical_vocab_density",
        "structural_preference",
        "section_header_style",
        "formality_register",
    ):
        merged[key] = new_sig.get(key, existing.get(key, _FALLBACK_SIGNATURE[key]))

    return merged


# ─── System-prompt generation ─────────────────────────────────────────────────

_HEDGING_PHRASES = {
    "low": "Avoid hedging language; state conclusions directly.",
    "moderate": "Use hedging language moderately (e.g., 'suggests', 'indicates', 'likely').",
    "high": "Hedge claims frequently with phrases like 'possibly', 'likely', 'it appears that'.",
}
_TECH_PHRASES = {
    "low": "Use plain, accessible language. Avoid technical jargon.",
    "moderate": "Balance technical precision with accessibility.",
    "high": "Use precise technical vocabulary and domain-specific terminology.",
}
_STRUCT_PHRASES = {
    "bullets": "Present information using bullet points and numbered lists where possible.",
    "prose": "Write in flowing prose paragraphs. Minimise use of bullet lists.",
    "mixed": "Mix prose paragraphs with bullet lists where appropriate.",
}
_HEADER_PHRASES = {
    "numbered": "Use numbered section headers (e.g., '1. Introduction', '2. Analysis').",
    "plain": "Use plain section headers without numbering or decoration.",
    "bold": "Use bold section headers (e.g., '**Introduction**').",
    "none": "Write continuously without section headers.",
}
_FORMALITY_PHRASES = {
    "informal": "Write in a conversational, accessible tone. Contractions are fine.",
    "neutral": "Maintain a balanced, professional tone.",
    "formal": "Write in a formal, academic or executive register. Avoid contractions.",
}


def generate_voice_system_prompt(sig: dict[str, Any]) -> str:
    """Convert a style signature into a natural-language system-prompt addendum."""
    avg_sent = sig.get("avg_sentence_length", 20.0)
    avg_para = sig.get("avg_paragraph_length", 4.0)

    lines = [
        "## Writing Style Instructions",
        f"Write to match the author's calibrated voice:",
        f"- Target approximately {round(avg_sent)} words per sentence "
        f"and {round(avg_para)} sentences per paragraph.",
        f"- {_HEDGING_PHRASES.get(sig.get('hedging_frequency', 'moderate'), '')}",
        f"- {_TECH_PHRASES.get(sig.get('technical_vocab_density', 'moderate'), '')}",
        f"- {_STRUCT_PHRASES.get(sig.get('structural_preference', 'prose'), '')}",
        f"- {_HEADER_PHRASES.get(sig.get('section_header_style', 'plain'), '')}",
        f"- {_FORMALITY_PHRASES.get(sig.get('formality_register', 'formal'), '')}",
    ]
    return "\n".join(lines)
