# 2026-11-23 PDF attachments return text instead of base64 (PRD-22360)

`autotask_get_ticket_attachment` and `autotask_get_ticket_note_attachment` with `includeData=true`
now return the text of a PDF instead of its base64 content, so an agent can read it.

- New module `src/autotask_mcp/pdf_text.py` (uses `pypdf`, no Autotask imports): filled form fields
  as `- <label>: <value>` (label = tooltip, else a non-generic field name, else the nearest text to
  the left or above, else the field name; checkboxes `checked` / `not checked`), then the page text
  with table rows on one line as `Label | Value`.
- Result fields for a PDF: `text`, `textFound`, `pages`, `formFields`, `summary`; `textTruncated` and
  `textLength` when cut. No `data`.
- Image-only PDF: success with `textFound: false` and a `message` naming the file ("No text found
  in <file> (image-only PDF, N pages). OCR is not supported."). Corrupt, password-protected, over
  10 MiB or slow (20 s) PDFs also return a `message`, never an error and never base64. Only the
  first 100 pages are read (a note says so).
- New optional parameters on both tools: `includeRawPdf` (base64 as before) and `maxTextChars`
  (default 60,000, minimum 1,000). Non-PDF files (images) are unchanged.
- Dependencies: `pypdf` (runtime), `reportlab` (dev only, builds the test PDFs).

Behaviour change: a consumer that relied on base64 `data` for a PDF now gets `text` unless it passes
`includeRawPdf=true`.
