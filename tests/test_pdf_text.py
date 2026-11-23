# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""PDF text extraction on generated PDFs (dummy data only). PRD-22360."""

from io import BytesIO

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from autotask_mcp.pdf_text import read_pdf

ANSWER_KEY = {
    "Full name": "Jane Example",
    "Email address": "jane.example@example.test",
    "Division": "North",
    "License": "Business Premium",
    "Email & Security Groups": "Sales Team; VPN Users",
    "Additional requested groups": "Finance Readers",
}


def _pdf(draw) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    draw(c)
    c.save()
    return buf.getvalue()


def _form_pdf(names=None, tooltips=True, label_text=True) -> bytes:
    keys = list(ANSWER_KEY)
    names = names or keys

    def draw(c):
        for i, key in enumerate(keys):
            y = 700 - i * 40
            if label_text:
                c.drawString(50, y + 4, key)
            c.acroForm.textfield(
                name=names[i],
                tooltip=key if tooltips else None,
                value=ANSWER_KEY[key],
                x=250,
                y=y,
                width=250,
                height=20,
                forceBorder=True,
            )

    return _pdf(draw)


def _table_pdf() -> bytes:
    def draw(c):
        for i, (k, v) in enumerate(ANSWER_KEY.items()):
            c.drawString(50, 700 - i * 25, k)
            c.drawString(300, 700 - i * 25, v)

    return _pdf(draw)


def test_form_fields_exact_values():
    out = read_pdf(_form_pdf(), "form.pdf", max_chars=60_000)
    assert out.found and out.form_fields == 6
    for key, value in ANSWER_KEY.items():
        assert f"- {key}: {value}" in out.text


def test_checkbox_values():
    def draw(c):
        c.drawString(100, 705, "Equipment")
        c.acroForm.checkbox(name="agree", tooltip="Needs laptop", checked=True, x=50, y=700)
        c.acroForm.checkbox(name="other", tooltip="Needs phone", checked=False, x=50, y=650)

    out = read_pdf(_pdf(draw), "boxes.pdf", max_chars=60_000)
    assert "- Needs laptop: checked" in out.text
    assert "- Needs phone: not checked" in out.text


def test_table_rows_label_next_to_value():
    out = read_pdf(_table_pdf(), "table.pdf", max_chars=60_000)
    assert out.found
    lines = out.text.splitlines()
    for key, value in ANSWER_KEY.items():
        assert f"{key} | {value}" in lines


def test_generic_field_names_get_labels():
    generic = [f"Text{i}" for i in range(1, 7)]
    # tooltip present
    out = read_pdf(_form_pdf(names=generic), "g.pdf", max_chars=60_000)
    assert "- Division: North" in out.text
    # no tooltip: nearest text on the left of the field
    out = read_pdf(_form_pdf(names=generic, tooltips=False), "g.pdf", max_chars=60_000)
    for key, value in ANSWER_KEY.items():
        assert f"- {key}: {value}" in out.text

    # no tooltip, label printed above the field
    def draw(c):
        c.drawString(250, 730, "Work phone")
        c.acroForm.textfield(name="Text1", value="555-0100", x=250, y=705, width=150, height=20)

    out = read_pdf(_pdf(draw), "above.pdf", max_chars=60_000)
    assert "- Work phone: 555-0100" in out.text

    # nothing near the field: fall back to the field name
    def lonely(c):
        c.drawString(50, 750, "Header")
        c.acroForm.textfield(name="Text9", value="x", x=250, y=300, width=50, height=20)

    out = read_pdf(_pdf(lonely), "lonely.pdf", max_chars=60_000)
    assert "- Text9: x" in out.text


def test_image_only_pdf_message():
    def draw(c):
        c.rect(50, 50, 200, 200, fill=1)  # vector shape only, no text layer

    out = read_pdf(_pdf(draw), "scan-0042.pdf", max_chars=60_000)
    assert not out.found and out.text == ""
    assert "No text found in scan-0042.pdf" in out.message and "1 page" in out.message


def test_corrupt_pdf_message():
    out = read_pdf(b"%PDF-1.4 garbage", "bad.pdf", max_chars=60_000)
    assert not out.found and "bad.pdf" in out.message and "could not be read" in out.message


def test_encrypted_pdf_message():
    w = PdfWriter(clone_from=PdfReader(BytesIO(_table_pdf())))
    w.encrypt("secret", algorithm="RC4-128")
    buf = BytesIO()
    w.write(buf)
    out = read_pdf(buf.getvalue(), "locked.pdf", max_chars=60_000)
    assert not out.found and "locked.pdf" in out.message and "password-protected" in out.message


def test_text_truncated():
    out = read_pdf(_table_pdf(), "t.pdf", max_chars=100)
    assert out.truncated and len(out.text) == 100 and out.length > 100


def test_page_limit_note():
    def draw(c):
        for i in range(101):
            c.drawString(50, 700, f"Line {i}")
            c.showPage()

    out = read_pdf(_pdf(draw), "long.pdf", max_chars=1_000_000)
    assert out.pages == 101 and "first 100 of 101 pages" in out.text and "Line 99" in out.text
    assert "Line 100" not in out.text
