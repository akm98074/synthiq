"""
Phase 6: Export pipeline — DOCX and PDF builders.

Public API:
  build_docx(sections, project_name, deliverable_type, **options) -> bytes
  build_pdf(sections, project_name, deliverable_type, **options) -> bytes

Both functions accept:
  citation_style: "inline" | "footnotes"
  include_source_map: bool
  source_map: dict | None    (used when include_source_map=True)
"""
from __future__ import annotations

import io
import re
from html import escape as _html_escape
from typing import Any

# ─── Shared regex ─────────────────────────────────────────────────────────────

_CITATION_RE = re.compile(r"\[Source\s+(\d+)(?:,\s*p\.?\s*(\d+))?\]", re.IGNORECASE)


# ─── DOCX ─────────────────────────────────────────────────────────────────────


def build_docx(
    sections: list[dict[str, Any]],
    project_name: str,
    deliverable_type: str,
    citation_style: str = "inline",
    include_source_map: bool = False,
    source_map: dict[str, Any] | None = None,
) -> bytes:
    """
    Render deliverable sections as a styled .docx file.

    Returns raw bytes suitable for writing to disk or streaming to a client.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()

    # ── Page margins ───────────────────────────────────────────────────────────
    for sec in doc.sections:
        sec.top_margin = Inches(1)
        sec.bottom_margin = Inches(1)
        sec.left_margin = Inches(1.25)
        sec.right_margin = Inches(1.25)

    # ── Title block ────────────────────────────────────────────────────────────
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title_run = title_para.add_run(project_name)
    title_run.font.size = Pt(22)
    title_run.font.bold = True

    type_label = deliverable_type.replace("_", " ").title()
    sub_para = doc.add_paragraph(type_label)
    sub_para.runs[0].font.size = Pt(12)
    sub_para.runs[0].font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

    doc.add_paragraph()  # spacer

    # ── Sections ───────────────────────────────────────────────────────────────
    citation_counter = [0]

    for s in sections:
        heading_para = doc.add_heading(s.get("title", ""), level=1)
        if heading_para.runs:
            heading_para.runs[0].font.size = Pt(14)

        _html_to_docx(
            doc,
            html=s.get("content", ""),
            citation_style=citation_style,
            counter=citation_counter,
        )

        # Per-section references block when using footnotes style
        if citation_style == "footnotes":
            citations = s.get("citations") or []
            if citations:
                ref_para = doc.add_paragraph()
                ref_run = ref_para.add_run("References")
                ref_run.bold = True
                ref_run.font.size = Pt(9)
                ref_run.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)
                for c in citations:
                    lbl = c.get("source_title", "")
                    if c.get("page"):
                        lbl += f", p.{c['page']}"
                    rp = doc.add_paragraph(style="List Number")
                    rp.add_run(lbl).font.size = Pt(9)

        doc.add_paragraph()  # section spacer

    # ── Source Map appendix ────────────────────────────────────────────────────
    if include_source_map and source_map:
        _docx_source_map_appendix(doc, source_map)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _html_to_docx(
    doc: Any,
    html: str,
    citation_style: str,
    counter: list[int],
) -> None:
    """Parse section HTML and append corresponding DOCX elements."""
    from bs4 import BeautifulSoup
    from docx.shared import Pt

    soup = BeautifulSoup(html or "", "html.parser")

    for elem in soup.children:
        tag = getattr(elem, "name", None)
        if tag is None:
            # Bare text node — skip whitespace-only
            text = str(elem).strip()
            if text:
                p = doc.add_paragraph()
                p.add_run(_process_citations(text, citation_style, counter)).font.size = Pt(11)
            continue

        raw_text = elem.get_text(separator=" ", strip=True)
        if not raw_text:
            continue

        if tag in ("h3", "h4", "h5"):
            level = {"h3": 2, "h4": 2, "h5": 3}.get(tag, 2)
            hpara = doc.add_heading(raw_text, level=level)
            if hpara.runs:
                hpara.runs[0].font.size = Pt(12)

        elif tag == "ul":
            for li in elem.find_all("li"):
                li_text = _process_citations(
                    li.get_text(separator=" ", strip=True),
                    citation_style,
                    counter,
                )
                p = doc.add_paragraph(style="List Bullet")
                p.add_run(li_text).font.size = Pt(11)

        elif tag == "p":
            content = _process_citations(raw_text, citation_style, counter)
            p = doc.add_paragraph()
            p.add_run(content).font.size = Pt(11)

        else:
            content = _process_citations(raw_text, citation_style, counter)
            if content:
                p = doc.add_paragraph()
                p.add_run(content).font.size = Pt(11)


def _process_citations(text: str, citation_style: str, counter: list[int]) -> str:
    """Transform citation markers based on style."""
    if citation_style == "inline":
        # Strip any HTML from the text, keep the marker text as-is
        return re.sub(r"<[^>]+>", "", text)

    # footnotes: replace [Source N, p.X] with [counter]
    def _replace(m: re.Match) -> str:
        counter[0] += 1
        return f"[{counter[0]}]"

    clean = re.sub(r"<[^>]+>", "", text)
    return _CITATION_RE.sub(_replace, clean)


def _docx_source_map_appendix(doc: Any, source_map: dict[str, Any]) -> None:
    """Add Source Map appendix tables to the document."""
    from docx.shared import Pt

    doc.add_page_break()
    doc.add_heading("Appendix: Source Map", level=1)

    clusters = source_map.get("clusters") or []
    if clusters:
        doc.add_heading("Clusters", level=2)
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Cluster"
        hdr[1].text = "Key Entities"
        hdr[2].text = "Sources"
        for c in clusters:
            row = table.add_row().cells
            row[0].text = str(c.get("label", ""))
            row[1].text = ", ".join((c.get("key_entities") or [])[:5])
            row[2].text = str(c.get("source_count", 0))
        doc.add_paragraph()

    contradictions = source_map.get("contradictions") or []
    if contradictions:
        doc.add_heading("Contradictions", level=2)
        table = doc.add_table(rows=1, cols=3)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "Entity"
        hdr[1].text = "Source A"
        hdr[2].text = "Source B"
        for c in contradictions:
            row = table.add_row().cells
            row[0].text = str(c.get("entity", ""))
            row[1].text = str(c.get("source_a", ""))
            row[2].text = str(c.get("source_b", ""))
        doc.add_paragraph()

    gaps = source_map.get("gaps") or []
    if gaps:
        doc.add_heading("Research Gaps", level=2)
        for g in gaps:
            topic = g.get("topic", "")
            mentioned = g.get("mentioned_in_count", 0)
            missing = g.get("missing_in_count", 0)
            p = doc.add_paragraph(style="List Bullet")
            p.add_run(
                f"{topic}: in {mentioned} source(s), missing from {missing}"
            ).font.size = Pt(11)


# ─── PDF ──────────────────────────────────────────────────────────────────────


def build_pdf(
    sections: list[dict[str, Any]],
    project_name: str,
    deliverable_type: str,
    citation_style: str = "inline",
    include_source_map: bool = False,
    source_map: dict[str, Any] | None = None,
) -> bytes:
    """
    Render deliverable sections as a PDF via weasyprint.

    Falls back to returning the HTML bytes with an .html MIME type if
    weasyprint is unavailable (e.g. missing system libraries).
    """
    html = build_pdf_html(
        sections=sections,
        project_name=project_name,
        deliverable_type=deliverable_type,
        citation_style=citation_style,
        include_source_map=include_source_map,
        source_map=source_map,
    )
    try:
        import weasyprint  # noqa: PLC0415
        return weasyprint.HTML(string=html).write_pdf()
    except Exception:
        return html.encode("utf-8")


def build_pdf_html(
    sections: list[dict[str, Any]],
    project_name: str,
    deliverable_type: str,
    citation_style: str = "inline",
    include_source_map: bool = False,
    source_map: dict[str, Any] | None = None,
) -> str:
    """
    Build a standalone HTML string suitable for weasyprint PDF rendering.

    Exposed separately so it can be tested without weasyprint installed.
    """
    type_label = deliverable_type.replace("_", " ").title()
    body_parts: list[str] = [
        f'<h1 class="doc-title">{_esc(project_name)}</h1>',
        f'<p class="doc-type">{_esc(type_label)}</p>',
    ]

    citation_counter = [0]

    for s in sections:
        title = _esc(s.get("title", ""))
        content_html = s.get("content", "")
        citations: list[dict] = s.get("citations") or []

        if citation_style == "footnotes":
            content_html = _inline_to_superscript(content_html, citation_counter)
            refs_html = _citations_to_html(citations)
        else:
            refs_html = ""

        body_parts.append(
            f'<div class="section">'
            f"<h2>{title}</h2>"
            f"{content_html}"
            f"{refs_html}"
            f"</div>"
        )

    if include_source_map and source_map:
        body_parts.append(_source_map_to_html(source_map))

    return _HTML_TEMPLATE.format(
        css=_PDF_CSS,
        body="\n".join(body_parts),
    )


def _inline_to_superscript(html: str, counter: list[int]) -> str:
    """Replace [Source N, p.X] citation markers with superscript numbers."""

    def _replace(m: re.Match) -> str:
        counter[0] += 1
        return f'<sup class="citation-ref">[{counter[0]}]</sup>'

    return _CITATION_RE.sub(_replace, html)


def _citations_to_html(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return ""
    items = []
    for c in citations:
        lbl = _esc(c.get("source_title", ""))
        if c.get("page"):
            lbl += f", p.{c['page']}"
        items.append(f"<li>{lbl}</li>")
    return (
        '<div class="references">'
        '<h4>References</h4>'
        f"<ol>{''.join(items)}</ol>"
        "</div>"
    )


def _source_map_to_html(source_map: dict[str, Any]) -> str:
    parts = ['<div class="appendix-page"><h2>Appendix: Source Map</h2>']

    clusters = source_map.get("clusters") or []
    if clusters:
        parts.append("<h3>Clusters</h3>")
        parts.append(
            "<table><thead><tr>"
            "<th>Cluster</th><th>Key Entities</th><th>Sources</th>"
            "</tr></thead><tbody>"
        )
        for c in clusters:
            label = _esc(str(c.get("label", "")))
            entities = _esc(", ".join((c.get("key_entities") or [])[:5]))
            src_count = c.get("source_count", 0)
            parts.append(
                f"<tr><td>{label}</td><td>{entities}</td><td>{src_count}</td></tr>"
            )
        parts.append("</tbody></table>")

    contradictions = source_map.get("contradictions") or []
    if contradictions:
        parts.append("<h3>Contradictions</h3>")
        parts.append(
            "<table><thead><tr>"
            "<th>Entity</th><th>Source A</th><th>Source B</th>"
            "</tr></thead><tbody>"
        )
        for c in contradictions:
            entity = _esc(str(c.get("entity", "")))
            sa = _esc(str(c.get("source_a", "")))
            sb = _esc(str(c.get("source_b", "")))
            parts.append(f"<tr><td>{entity}</td><td>{sa}</td><td>{sb}</td></tr>")
        parts.append("</tbody></table>")

    gaps = source_map.get("gaps") or []
    if gaps:
        parts.append("<h3>Research Gaps</h3><ul>")
        for g in gaps:
            topic = _esc(str(g.get("topic", "")))
            mentioned = g.get("mentioned_in_count", 0)
            missing = g.get("missing_in_count", 0)
            parts.append(
                f"<li>{topic}: in {mentioned} source(s), missing from {missing}</li>"
            )
        parts.append("</ul>")

    parts.append("</div>")
    return "\n".join(parts)


def _esc(text: str) -> str:
    return _html_escape(str(text))


# ─── HTML template + CSS ──────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>"""

_PDF_CSS = """
@page {
    size: A4;
    margin: 2.5cm 2.5cm 2.5cm 2.5cm;
    @bottom-center {
        content: counter(page);
        font-size: 9pt;
        color: #94a3b8;
    }
}
body {
    font-family: Georgia, 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.7;
    color: #1e293b;
}
h1.doc-title {
    font-size: 22pt;
    color: #0f172a;
    margin-bottom: 0;
    border: none;
}
p.doc-type {
    font-size: 11pt;
    color: #64748b;
    margin-top: 4pt;
    margin-bottom: 32pt;
}
h2 {
    font-size: 14pt;
    color: #1e293b;
    margin-top: 24pt;
    margin-bottom: 8pt;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 4pt;
}
h3 { font-size: 12pt; color: #334155; margin-top: 16pt; margin-bottom: 6pt; }
h4 { font-size: 11pt; color: #475569; margin-top: 12pt; margin-bottom: 4pt; }
p { margin: 0 0 10pt 0; text-align: justify; }
ul { margin: 6pt 0 10pt 20pt; padding: 0; }
li { margin-bottom: 3pt; }
sup.citation-ref {
    color: #6366f1;
    font-size: 8pt;
    vertical-align: super;
}
.section { margin-bottom: 28pt; }
.references {
    margin-top: 12pt;
    border-top: 1px solid #e2e8f0;
    padding-top: 8pt;
}
.references h4 { font-size: 9pt; color: #64748b; margin-bottom: 4pt; }
.references ol { font-size: 9pt; color: #475569; margin: 0 0 0 16pt; }
.appendix-page { page-break-before: always; }
table {
    width: 100%;
    border-collapse: collapse;
    margin: 10pt 0 20pt;
    font-size: 10pt;
}
th {
    background: #f1f5f9;
    padding: 6pt 8pt;
    text-align: left;
    border: 1px solid #cbd5e1;
    font-weight: bold;
}
td { padding: 5pt 8pt; border: 1px solid #e2e8f0; vertical-align: top; }
"""
