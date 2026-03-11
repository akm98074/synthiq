"""Tests for pipeline/exporter.py"""
from __future__ import annotations

import io
import zipfile

import pytest

from pipeline.exporter import (
    _citations_to_html,
    _esc,
    _html_to_docx,
    _inline_to_superscript,
    _process_citations,
    _source_map_to_html,
    build_docx,
    build_pdf_html,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SECTIONS = [
    {
        "id": "s1",
        "title": "Executive Summary",
        "content": "<p class=\"mb-3\">The market grew significantly [Source 1, p.5] in 2023.</p>",
        "status": "done",
        "citations": [
            {"source_id": "src-a", "source_title": "Market Report", "page": 5}
        ],
    },
    {
        "id": "s2",
        "title": "Key Findings",
        "content": (
            "<h4>Subsection</h4>"
            "<p class=\"mb-3\">Competition increased [Source 2]. "
            "Regulation also shifted [Source 1].</p>"
            "<ul class=\"list-disc ml-5\"><li>Finding one [Source 2]</li></ul>"
        ),
        "status": "done",
        "citations": [
            {"source_id": "src-b", "source_title": "Competitive Brief", "page": None},
            {"source_id": "src-a", "source_title": "Market Report", "page": 12},
        ],
    },
]

SOURCE_MAP = {
    "clusters": [
        {
            "id": "c1",
            "label": "Market Dynamics",
            "chunk_count": 5,
            "source_count": 2,
            "key_entities": ["MarketSize", "Competition"],
        }
    ],
    "contradictions": [
        {
            "id": "con1",
            "entity": "MarketSize",
            "claim": "differs",
            "source_a": "Market Report",
            "source_b": "Competitive Brief",
        }
    ],
    "gaps": [
        {
            "topic": "Pricing Strategy",
            "mentioned_in_count": 2,
            "missing_in_count": 1,
        }
    ],
}


# ─── _esc ─────────────────────────────────────────────────────────────────────


def test_esc_escapes_html():
    assert _esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
    assert _esc("R&D") == "R&amp;D"
    assert _esc('"quote"') == "&quot;quote&quot;"


def test_esc_handles_non_string():
    assert _esc(42) == "42"
    assert _esc(None) == "None"


# ─── _process_citations ───────────────────────────────────────────────────────


def test_process_citations_inline_keeps_marker():
    counter = [0]
    result = _process_citations("[Source 1, p.5] growth", "inline", counter)
    assert "[Source 1, p.5]" in result
    assert counter[0] == 0  # counter not incremented in inline mode


def test_process_citations_footnotes_replaces_with_number():
    counter = [0]
    result = _process_citations("[Source 1, p.5] growth", "footnotes", counter)
    assert "[1]" in result
    assert "[Source" not in result
    assert counter[0] == 1


def test_process_citations_footnotes_increments_globally():
    counter = [3]  # simulate already having 3 footnotes
    result = _process_citations("[Source 2] data [Source 1, p.5]", "footnotes", counter)
    assert "[4]" in result
    assert "[5]" in result
    assert counter[0] == 5


def test_process_citations_strips_html_tags():
    counter = [0]
    result = _process_citations('<cite class="x">[Source 1]</cite>', "inline", counter)
    assert "<cite" not in result
    assert "[Source 1]" in result


# ─── _inline_to_superscript ───────────────────────────────────────────────────


def test_inline_to_superscript_replaces_markers():
    counter = [0]
    html = "<p>Growth [Source 1, p.3] was strong [Source 2].</p>"
    result = _inline_to_superscript(html, counter)
    assert '<sup class="citation-ref">[1]</sup>' in result
    assert '<sup class="citation-ref">[2]</sup>' in result
    assert "[Source" not in result
    assert counter[0] == 2


def test_inline_to_superscript_does_not_alter_non_citation_text():
    counter = [0]
    html = "<p>No citations here.</p>"
    result = _inline_to_superscript(html, counter)
    assert result == html
    assert counter[0] == 0


# ─── _citations_to_html ───────────────────────────────────────────────────────


def test_citations_to_html_empty():
    result = _citations_to_html([])
    assert result == ""


def test_citations_to_html_with_page():
    citations = [{"source_title": "Report A", "page": 5}]
    result = _citations_to_html(citations)
    assert "Report A" in result
    assert "p.5" in result
    assert "<ol>" in result


def test_citations_to_html_without_page():
    citations = [{"source_title": "Report B", "page": None}]
    result = _citations_to_html(citations)
    assert "Report B" in result
    assert "p." not in result


# ─── _source_map_to_html ──────────────────────────────────────────────────────


def test_source_map_to_html_includes_cluster():
    result = _source_map_to_html(SOURCE_MAP)
    assert "Market Dynamics" in result
    assert "MarketSize" in result


def test_source_map_to_html_includes_contradiction():
    result = _source_map_to_html(SOURCE_MAP)
    assert "MarketSize" in result
    assert "Market Report" in result
    assert "Competitive Brief" in result


def test_source_map_to_html_includes_gap():
    result = _source_map_to_html(SOURCE_MAP)
    assert "Pricing Strategy" in result
    assert "appendix-page" in result


def test_source_map_to_html_escapes_html_entities():
    sm = {"clusters": [{"label": "<script>", "chunk_count": 1, "source_count": 1, "key_entities": []}]}
    result = _source_map_to_html(sm)
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


# ─── build_pdf_html ───────────────────────────────────────────────────────────


def test_build_pdf_html_structure():
    html = build_pdf_html(
        sections=SECTIONS,
        project_name="My Report",
        deliverable_type="executive_memo",
    )
    assert "<!DOCTYPE html>" in html
    assert "My Report" in html
    assert "Executive Memo" in html  # type label formatted
    assert "Executive Summary" in html
    assert "Key Findings" in html


def test_build_pdf_html_inline_citations_preserved():
    html = build_pdf_html(
        sections=SECTIONS,
        project_name="Report",
        deliverable_type="executive_memo",
        citation_style="inline",
    )
    assert "[Source 1, p.5]" in html
    # In inline mode no superscript elements should appear (CSS class in <style> is fine)
    assert '<sup class="citation-ref">' not in html


def test_build_pdf_html_footnotes_converts_citations():
    html = build_pdf_html(
        sections=SECTIONS,
        project_name="Report",
        deliverable_type="executive_memo",
        citation_style="footnotes",
    )
    assert "citation-ref" in html
    assert "[Source 1, p.5]" not in html
    assert "References" in html


def test_build_pdf_html_with_source_map_appendix():
    html = build_pdf_html(
        sections=SECTIONS,
        project_name="Report",
        deliverable_type="competitive_landscape",
        include_source_map=True,
        source_map=SOURCE_MAP,
    )
    assert "Appendix: Source Map" in html
    assert "Market Dynamics" in html
    assert "Pricing Strategy" in html


def test_build_pdf_html_without_source_map():
    html = build_pdf_html(
        sections=SECTIONS,
        project_name="Report",
        deliverable_type="competitive_landscape",
        include_source_map=False,
    )
    assert "Appendix" not in html


# ─── build_docx ───────────────────────────────────────────────────────────────


def test_build_docx_returns_bytes():
    result = build_docx(
        sections=SECTIONS,
        project_name="Test Project",
        deliverable_type="executive_memo",
    )
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_docx_is_valid_zip():
    """DOCX files are ZIP archives — verify the output is parseable."""
    result = build_docx(
        sections=SECTIONS,
        project_name="Test Project",
        deliverable_type="executive_memo",
    )
    buf = io.BytesIO(result)
    assert zipfile.is_zipfile(buf)


def test_build_docx_contains_content():
    """Open the DOCX and verify section titles are in the document XML."""
    result = build_docx(
        sections=SECTIONS,
        project_name="Test Project",
        deliverable_type="executive_memo",
    )
    buf = io.BytesIO(result)
    with zipfile.ZipFile(buf) as zf:
        with zf.open("word/document.xml") as f:
            content = f.read().decode("utf-8")
    assert "Executive Summary" in content
    assert "Key Findings" in content


def test_build_docx_footnotes_citation_style():
    result = build_docx(
        sections=SECTIONS,
        project_name="Test",
        deliverable_type="executive_memo",
        citation_style="footnotes",
    )
    assert isinstance(result, bytes)
    # Verify it's a valid docx
    buf = io.BytesIO(result)
    assert zipfile.is_zipfile(buf)


def test_build_docx_with_source_map_appendix():
    result = build_docx(
        sections=SECTIONS,
        project_name="Test",
        deliverable_type="competitive_landscape",
        include_source_map=True,
        source_map=SOURCE_MAP,
    )
    buf = io.BytesIO(result)
    with zipfile.ZipFile(buf) as zf:
        with zf.open("word/document.xml") as f:
            content = f.read().decode("utf-8")
    assert "Source Map" in content
    assert "Market Dynamics" in content


def test_build_docx_empty_sections():
    result = build_docx(
        sections=[],
        project_name="Empty",
        deliverable_type="project_brief",
    )
    assert isinstance(result, bytes)
    assert len(result) > 0
