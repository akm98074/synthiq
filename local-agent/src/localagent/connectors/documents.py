"""Documents connector: create PDF and Excel files the user can open and share."""
from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..tools.base import Tool, ToolError, ToolResult, obj, s

UNICODE_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
ASCII_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                           "…": "...", "•": "-", " ": " "})


def safe_name(title: str) -> str:
    name = re.sub(r"[^\w\- ]+", "", title).strip() or "document"
    return name[:80]


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stem}{suffix}"
    n = 2
    while path.exists():
        path = folder / f"{stem} ({n}){suffix}"
        n += 1
    return path


def write_pdf(path: Path, title: str, content: str) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    font = next((f for f in UNICODE_FONTS if Path(f).exists()), None)
    if font:
        pdf.add_font("Body", "", font)
        family, clean = "Body", (lambda t: t)
    else:
        family = "Helvetica"
        clean = lambda t: t.translate(ASCII_MAP).encode("latin-1", "replace").decode("latin-1")  # noqa: E731
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font(family, size=20)
    pdf.multi_cell(width, 10, clean(title))
    pdf.set_font(family, size=9)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(width, 6, clean(datetime.now().strftime("%d %B %Y")))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    for line in content.splitlines():
        stripped = line.strip()
        pdf.set_x(pdf.l_margin)
        if not stripped:
            pdf.ln(4)
        elif stripped.startswith("### "):
            pdf.set_font(family, size=12)
            pdf.multi_cell(width, 7, clean(stripped[4:]))
        elif stripped.startswith("## "):
            pdf.set_font(family, size=14)
            pdf.ln(2)
            pdf.multi_cell(width, 8, clean(stripped[3:]))
        elif stripped.startswith("# "):
            pdf.set_font(family, size=16)
            pdf.ln(2)
            pdf.multi_cell(width, 9, clean(stripped[2:]))
        elif stripped[:2] in ("- ", "* "):
            pdf.set_font(family, size=11)
            pdf.multi_cell(width, 6, clean("•  " if font else "-  ") + clean(stripped[2:].replace("**", "")))
        else:
            pdf.set_font(family, size=11)
            pdf.multi_cell(width, 6, clean(stripped.replace("**", "")))
    pdf.output(str(path))


def write_xlsx(path: Path, title: str, csv_text: str) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    rows = [r for r in csv.reader(io.StringIO(csv_text.strip())) if any(c.strip() for c in r)]
    if not rows:
        raise ToolError("The spreadsheet has no rows. Pass CSV text with a header row.")
    wb = Workbook()
    ws = wb.active
    ws.title = safe_name(title)[:31] or "Sheet1"
    for r in rows:
        ws.append([_cell(c) for c in r])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    ws.freeze_panes = "A2"
    wb.save(str(path))
    return len(rows) - 1


def _cell(value: str):
    v = value.strip()
    try:
        return int(v) if re.fullmatch(r"-?\d+", v) else float(v) if re.fullmatch(r"-?\d+\.\d+", v) else v
    except ValueError:
        return v


def _reveal(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def document_tools(folder: Path) -> list[Tool]:
    def pdf(a: dict) -> ToolResult:
        path = unique_path(folder, safe_name(a["title"]), ".pdf")
        write_pdf(path, a["title"], a["content"])
        _reveal(path)
        return ToolResult(f"Saved PDF to {path}.", f"PDF saved: {path.name}", {"path": str(path)})

    def xlsx(a: dict) -> ToolResult:
        path = unique_path(folder, safe_name(a["title"]), ".xlsx")
        n = write_xlsx(path, a["title"], a["csv"])
        _reveal(path)
        return ToolResult(f"Saved spreadsheet with {n} data row(s) to {path}.",
                          f"Spreadsheet saved: {path.name}", {"path": str(path), "rows": n})

    return [
        Tool("documents_create_pdf",
             "Save a document as a PDF in ~/Documents/LocalAIAgent. Content may use '# ' headings and '- ' bullets.",
             obj({"title": s("Document title"), "content": s("Full document text")}, ["title", "content"]),
             "draft", "documents", pdf, lambda a: f"Create PDF “{a.get('title', '')}”", ("task", "computer_action")),
        Tool("documents_create_spreadsheet",
             "Save a table as an Excel spreadsheet in ~/Documents/LocalAIAgent.",
             obj({"title": s("Spreadsheet title"),
                  "csv": s("The table as CSV text; first line is the header row")}, ["title", "csv"]),
             "draft", "documents", xlsx, lambda a: f"Create spreadsheet “{a.get('title', '')}”",
             ("task", "computer_action")),
    ]
