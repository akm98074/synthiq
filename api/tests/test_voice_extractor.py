"""
Unit tests for pipeline/voice_extractor.py.

All Claude API calls are fully mocked — no real key needed.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ─── extract_style_signature ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_no_api_key_returns_fallback(monkeypatch):
    """Without an Anthropic key, should return the default fallback signature."""
    import config
    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = ""
    try:
        from pipeline.voice_extractor import extract_style_signature, _FALLBACK_SIGNATURE

        result = await extract_style_signature(MagicMock(), "Some text here.")
        assert result == _FALLBACK_SIGNATURE
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_extract_empty_text_returns_fallback():
    """Empty text should return the fallback without hitting the API."""
    import config
    config.settings.anthropic_api_key = "fake"
    try:
        from pipeline.voice_extractor import extract_style_signature, _FALLBACK_SIGNATURE

        result = await extract_style_signature(MagicMock(), "   ")
        assert result == _FALLBACK_SIGNATURE
    finally:
        config.settings.anthropic_api_key = ""


@pytest.mark.asyncio
async def test_extract_valid_response():
    """A valid JSON Claude response is parsed and returned correctly."""
    import config

    sig_data = {
        "avg_sentence_length": 22.5,
        "avg_paragraph_length": 5.0,
        "hedging_frequency": "low",
        "technical_vocab_density": "high",
        "structural_preference": "prose",
        "section_header_style": "numbered",
        "formality_register": "formal",
    }
    mock_content = MagicMock()
    mock_content.text = json.dumps(sig_data)
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake"
    try:
        from pipeline.voice_extractor import extract_style_signature

        result = await extract_style_signature(mock_client, "Sample writing text.")
        assert result["avg_sentence_length"] == pytest.approx(22.5)
        assert result["hedging_frequency"] == "low"
        assert result["technical_vocab_density"] == "high"
        assert result["formality_register"] == "formal"
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_extract_invalid_json_returns_fallback():
    """Invalid JSON from Claude should fall back to defaults silently."""
    import config

    mock_content = MagicMock()
    mock_content.text = "Not JSON at all!"
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake"
    try:
        from pipeline.voice_extractor import extract_style_signature, _FALLBACK_SIGNATURE

        result = await extract_style_signature(mock_client, "Some text.")
        assert result == _FALLBACK_SIGNATURE
    finally:
        config.settings.anthropic_api_key = original


# ─── _validate_signature ──────────────────────────────────────────────────────


def test_validate_clamps_sentence_length():
    from pipeline.voice_extractor import _validate_signature

    result = _validate_signature({"avg_sentence_length": 200.0})
    assert result["avg_sentence_length"] == pytest.approx(60.0)

    result2 = _validate_signature({"avg_sentence_length": 1.0})
    assert result2["avg_sentence_length"] == pytest.approx(5.0)


def test_validate_invalid_categorical_falls_back():
    from pipeline.voice_extractor import _validate_signature

    result = _validate_signature({
        "avg_sentence_length": 18.0,
        "avg_paragraph_length": 3.0,
        "hedging_frequency": "VERY_HIGH",          # invalid
        "technical_vocab_density": "medium",         # invalid
        "structural_preference": "paragraphs",       # invalid
        "section_header_style": "underline",         # invalid
        "formality_register": "academic",            # invalid
    })
    assert result["hedging_frequency"] == "moderate"
    assert result["technical_vocab_density"] == "moderate"
    assert result["structural_preference"] == "prose"
    assert result["section_header_style"] == "plain"
    assert result["formality_register"] == "formal"


# ─── merge_signatures ─────────────────────────────────────────────────────────


def test_merge_no_existing():
    """Merging into None should return new_sig unchanged."""
    from pipeline.voice_extractor import merge_signatures

    new_sig = {
        "avg_sentence_length": 20.0,
        "avg_paragraph_length": 4.0,
        "hedging_frequency": "low",
        "technical_vocab_density": "high",
        "structural_preference": "bullets",
        "section_header_style": "numbered",
        "formality_register": "formal",
    }
    result = merge_signatures(None, new_sig, 0)
    assert result == new_sig


def test_merge_averages_numerics():
    """Numeric fields should be averaged across samples."""
    from pipeline.voice_extractor import merge_signatures

    existing = {
        "avg_sentence_length": 20.0,
        "avg_paragraph_length": 4.0,
        "hedging_frequency": "moderate",
        "technical_vocab_density": "moderate",
        "structural_preference": "prose",
        "section_header_style": "plain",
        "formality_register": "formal",
    }
    new_sig = {
        "avg_sentence_length": 10.0,   # avg of 20.0 (1 sample) and 10.0 = 15.0
        "avg_paragraph_length": 2.0,   # avg of 4.0 and 2.0 = 3.0
        "hedging_frequency": "high",
        "technical_vocab_density": "low",
        "structural_preference": "bullets",
        "section_header_style": "numbered",
        "formality_register": "informal",
    }
    result = merge_signatures(existing, new_sig, 1)
    assert result["avg_sentence_length"] == pytest.approx(15.0)
    assert result["avg_paragraph_length"] == pytest.approx(3.0)
    # Categoricals should reflect new_sig (last-wins)
    assert result["hedging_frequency"] == "high"
    assert result["structural_preference"] == "bullets"
    assert result["formality_register"] == "informal"


def test_merge_three_samples():
    """After 3 samples the running average is correct."""
    from pipeline.voice_extractor import merge_signatures

    sig1 = {"avg_sentence_length": 10.0, "avg_paragraph_length": 2.0,
            "hedging_frequency": "low", "technical_vocab_density": "low",
            "structural_preference": "prose", "section_header_style": "none",
            "formality_register": "informal"}
    sig2 = {"avg_sentence_length": 20.0, "avg_paragraph_length": 4.0,
            "hedging_frequency": "moderate", "technical_vocab_density": "moderate",
            "structural_preference": "mixed", "section_header_style": "plain",
            "formality_register": "neutral"}
    sig3 = {"avg_sentence_length": 30.0, "avg_paragraph_length": 6.0,
            "hedging_frequency": "high", "technical_vocab_density": "high",
            "structural_preference": "bullets", "section_header_style": "numbered",
            "formality_register": "formal"}

    merged12 = merge_signatures(sig1, sig2, 1)          # avg = 15.0 / 3.0
    merged123 = merge_signatures(merged12, sig3, 2)      # avg = (15*2+30)/3=20 / (3*2+6)/3=4

    assert merged123["avg_sentence_length"] == pytest.approx(20.0)
    assert merged123["avg_paragraph_length"] == pytest.approx(4.0)


# ─── generate_voice_system_prompt ────────────────────────────────────────────


def test_generate_prompt_contains_key_instructions():
    from pipeline.voice_extractor import generate_voice_system_prompt

    sig = {
        "avg_sentence_length": 18.0,
        "avg_paragraph_length": 5.0,
        "hedging_frequency": "moderate",
        "technical_vocab_density": "high",
        "structural_preference": "prose",
        "section_header_style": "numbered",
        "formality_register": "formal",
    }
    prompt = generate_voice_system_prompt(sig)
    assert "18" in prompt
    assert "formal" in prompt.lower()
    assert "prose" in prompt.lower()
    assert "numbered" in prompt.lower()


def test_generate_prompt_is_string():
    from pipeline.voice_extractor import generate_voice_system_prompt, _FALLBACK_SIGNATURE

    result = generate_voice_system_prompt(_FALLBACK_SIGNATURE)
    assert isinstance(result, str)
    assert len(result) > 50


def test_generate_prompt_all_register_variants():
    from pipeline.voice_extractor import generate_voice_system_prompt

    for register in ("informal", "neutral", "formal"):
        sig = dict(
            avg_sentence_length=20.0,
            avg_paragraph_length=4.0,
            hedging_frequency="moderate",
            technical_vocab_density="moderate",
            structural_preference="prose",
            section_header_style="plain",
            formality_register=register,
        )
        prompt = generate_voice_system_prompt(sig)
        assert isinstance(prompt, str)
        assert len(prompt) > 20
