# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Readable text from PDF bytes: filled form fields (with labels) and page text (table rows on one line).

Self-contained (no Autotask imports) so another connector can reuse it. PRD-22360.
Untrusted input: never raises, never logs content; limits on pages and output size.
"""

import logging
import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

log = logging.getLogger(__name__)

MAX_PAGES = 100
_GENERIC_NAME = re.compile(r"^(text|check ?box|field|combo ?box|list ?box|radio ?button)[ _-]?\d*$", re.IGNORECASE)
_GAP = re.compile(r" {3,}")
_BLANKS = re.compile(r"\n{3,}")


@dataclass
class PdfText:
    text: str = ""
    found: bool = False
    pages: int = 0
    form_fields: int = 0
    truncated: bool = False
    length: int = 0
    message: str = ""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _inherited(obj, key):
    """Field attributes live on the field dict or on an ancestor (``/Parent``)."""
    for _ in range(16):
        if obj is None:
            return None
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
    return None


def _full_name(obj) -> str:
    parts = []
    for _ in range(16):
        if obj is None:
            break
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
    return ".".join(reversed(parts))


def _fragments(page) -> list[tuple[float, float, str]]:
    """Text runs with their (x, y) position on the page."""
    runs: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, _font, _size):
        if text and text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            runs.append((x, y, text.strip()))

    page.extract_text(visitor_text=visit)
    return runs


def _neighbour_label(runs, rect) -> str | None:
    """Nearest text left of the widget on the same line, else the nearest text above it."""
    x0, y0, x1, y1 = (float(v) for v in rect)
    mid, tol = (y0 + y1) / 2, max(y1 - y0, 8.0)
    left = [(x0 - x, t) for x, y, t in runs if abs(y - mid) <= tol and x < x0]
    if left:
        return min(left)[1]
    above = [(y - y1, t) for x, y, t in runs if y >= y1 - 1 and x <= x1 and y - y1 <= 40]
    return min(above)[1] if above else None


def _form_lines(reader: PdfReader, pages) -> list[str]:
    lines = []
    for page in pages:
        runs = None
        for ref in page.get("/Annots") or []:
            w = ref.get_object()
            if w.get("/Subtype") != "/Widget" or _inherited(w, "/FT") is None:
                continue
            name = _full_name(w)
            ftype = _inherited(w, "/FT")
            value = _inherited(w, "/V")
            if ftype == "/Btn":
                state = str(w.get("/AS") or value or "/Off")
                shown = "not checked" if state == "/Off" else "checked"
            elif value is None or not str(value).strip():
                continue
            else:
                shown = str(value).strip()
            label = _inherited(w, "/TU")
            if not label and name and not _GENERIC_NAME.match(name.rsplit(".", 1)[-1]):
                label = name.rsplit(".", 1)[-1]
            if not label and "/Rect" in w:
                runs = runs if runs is not None else _fragments(page)
                label = _neighbour_label(runs, w["/Rect"])
            lines.append(f"- {str(label or name).strip()}: {shown}")
    return lines


def _page_text(page) -> str:
    text = page.extract_text(extraction_mode="layout") or ""
    rows = [_GAP.sub(" | ", line.strip()) for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(rows)).strip()


def read_pdf(raw: bytes, name: str, *, max_chars: int) -> PdfText:
    try:
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(""):
            return PdfText(message=f"{name} is password-protected; its text was not read.")
        total = len(reader.pages)
        pages = list(reader.pages[:MAX_PAGES])
        fields = _form_lines(reader, pages)
        body = [t for t in (_page_text(p) for p in pages) if t]
    except Exception as exc:  # untrusted file: any parser failure becomes a message
        log.warning("unreadable PDF %s: %s", name, type(exc).__name__)
        return PdfText(message=f"{name} could not be read as a PDF ({type(exc).__name__}); its text was not read.")

    parts = []
    if fields:
        parts.append("Form fields:\n" + "\n".join(fields))
    parts += [f"Page {i}\n{t}" for i, t in enumerate(body, 1)] if len(body) > 1 else body
    text = "\n\n".join(parts)
    if total > MAX_PAGES:
        text += f"\n\nNote: only the first {MAX_PAGES} of {total} pages were read."
    found = bool(fields or body)
    out = PdfText(found=found, pages=total, form_fields=len(fields), length=len(text))
    if not found:
        out.message = (
            f"No text found in {name} (image-only PDF, {_plural(total, 'page')}). "
            "OCR is not supported. The attachment content is not returned."
        )
        return out
    out.truncated = len(text) > max_chars
    out.text = text[:max_chars]
    return out
