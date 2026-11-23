# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Ticket attachments and ticket note attachments.

Metadata is read from the parent-scoped child URL; file bytes (base64 ``data``) only come from
the top-level ``/TicketAttachments/{id}`` and ``/TicketNoteAttachments/{id}`` endpoints.
"""

import asyncio
import base64
import binascii
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import _json
from ..api import ApiError, AutotaskClient, build, clean, item_id, single_record
from ..config import Settings
from ..pdf_text import read_pdf
from ._common import CREATE, PAGE_SIZE, READ, Args, Opt, Req, ToolInputError, search, tool

MAX_UPLOAD_BYTES = 3 * 1024 * 1024  # Autotask limit for ticket attachments
DEFAULT_INLINE_BASE64 = 750_000
MIN_INLINE_BASE64 = 1024
MAX_PDF_BYTES = 10 * 1024 * 1024  # larger PDFs are not parsed
MAX_PDF_BASE64 = MAX_PDF_BYTES * 4 // 3 + 4
DEFAULT_PDF_TEXT = 60_000
MIN_PDF_TEXT = 1_000
PDF_TIMEOUT_S = 20

INCLUDE_DATA = Opt("includeData", bool, "Return the file content as base64 (default false: metadata only).")
MAX_INLINE = Opt(
    "maxInlineBase64Bytes",
    int,
    f"Largest base64 string returned inline (default {DEFAULT_INLINE_BASE64}, minimum {MIN_INLINE_BASE64}); "
    "larger content is omitted with dataOmittedReason.",
)
INCLUDE_RAW_PDF = Opt("includeRawPdf", bool, "For a PDF, return the base64 file instead of its extracted text.")
MAX_TEXT = Opt("maxTextChars", int, f"Longest PDF text returned (default {DEFAULT_PDF_TEXT}, minimum {MIN_PDF_TEXT}).")


def _is_pdf(data: str) -> bool:
    head = "".join(data[:64].split())[:8]
    try:
        return base64.b64decode(head, validate=True).startswith(b"%PDF-")
    except (binascii.Error, ValueError):
        return False


async def _pdf_result(out: dict, data: str, a: Args) -> str:
    """PRD-22360: a PDF is returned as readable text, never as base64."""
    name = str(out.get("title") or out.get("fullPath") or f"attachment {out.get('id')}")
    max_chars = max(int(a.get("maxTextChars", DEFAULT_PDF_TEXT)), MIN_PDF_TEXT)
    out["textFound"] = False
    if len(data) > MAX_PDF_BASE64:
        out["message"] = f"{name} is larger than {MAX_PDF_BYTES // (1024 * 1024)} MiB; its text was not read."
        return _json.dump(out)
    try:
        raw = base64.b64decode("".join(data.split()), validate=True)
        res = await asyncio.wait_for(asyncio.to_thread(read_pdf, raw, name, max_chars=max_chars), PDF_TIMEOUT_S)
    except (binascii.Error, ValueError):
        out["message"] = f"{name} could not be read as a PDF (invalid base64); its text was not read."
        return _json.dump(out)
    except TimeoutError:
        out["message"] = f"{name} took longer than {PDF_TIMEOUT_S} seconds to read; its text was not read."
        return _json.dump(out)
    if not res.found:
        out["message"] = res.message
        out["pages"] = res.pages
        return _json.dump(out)
    out.update(
        textFound=True,
        pages=res.pages,
        formFields=res.form_fields,
        summary=f"Text read from {name} - {res.pages} page{'' if res.pages == 1 else 's'} - "
        f"{res.form_fields} form field{'' if res.form_fields == 1 else 's'}",
        text=res.text,
    )
    if res.truncated:
        out.update(textTruncated=True, textLength=res.length)
    return _json.dump(out, max_chars=max_chars + 5_000)


async def _attachment(
    c: AutotaskClient, entity: str, parent_entity: str, parent_field: str, parent_id: int, att_id: int, a: Args
) -> str:
    if a.includeData:
        item = await c.get_item(entity, att_id)
    else:
        try:
            payload = await c.get(f"/{parent_entity}/{parent_id}/Attachments/{att_id}")
            item = single_record(payload, att_id)
        except ApiError as exc:
            if exc.status not in (404, 405):
                raise
            item = None
        if not item:
            item = await c.get_item(entity, att_id)
    owner = item.get(parent_field, item.get("parentID"))
    if owner is not None and int(owner) != int(parent_id):
        raise ApiError("not_found", f"Attachment {att_id} does not belong to {parent_field} {parent_id}.", False, 404)

    data = item.pop("data", None)
    out = clean(item)
    if a.includeData:
        cap = max(int(a.get("maxInlineBase64Bytes", DEFAULT_INLINE_BASE64)), MIN_INLINE_BASE64)
        if data and not a.get("includeRawPdf") and _is_pdf(data):
            return await _pdf_result(out, data, a)
        if not data:
            out["dataOmittedReason"] = "Autotask returned no file content for this attachment."
        elif len(data) > cap:
            out["dataOmittedReason"] = f"Content is {len(data)} base64 characters, above maxInlineBase64Bytes={cap}."
            out["dataLength"] = len(data)
        else:
            out["data"] = data
            # Binary content is the point of this call: allow it past the default result size limit.
            return _json.dump(out, max_chars=cap + 20_000)
    return _json.dump(out)


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_get_ticket_attachment",
        "Get a ticket attachment. By default only metadata is returned; includeData=true adds the file as base64 "
        "(above maxInlineBase64Bytes it is omitted with dataOmittedReason), but a PDF returns its extracted text "
        "instead (includeRawPdf=true for base64). The attachment must belong to ticketId.",
        READ,
        Req("ticketId", int, "Ticket ID the attachment belongs to."),
        Req("attachmentId", int, "Attachment ID."),
        INCLUDE_DATA,
        MAX_INLINE,
        INCLUDE_RAW_PDF,
        MAX_TEXT,
    )
    async def get_ticket_attachment(c: AutotaskClient, a: Args) -> Any:
        return await _attachment(c, "TicketAttachments", "Tickets", "ticketID", a.ticketId, a.attachmentId, a)

    @t(
        "autotask_search_ticket_attachments",
        "List the attachments of one ticket (metadata only).",
        READ,
        Req("ticketId", int, "Ticket ID."),
        PAGE_SIZE,
    )
    async def search_ticket_attachments(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "TicketAttachments", build(("eq", "parentID", a.ticketId)), a, drop={"data"})

    @t(
        "autotask_get_ticket_note_attachment",
        "Get an attachment on a ticket note (e.g. a screenshot pasted into a note), not on the ticket itself. "
        "Metadata by default; includeData=true adds the base64 content (a PDF returns its extracted text instead; "
        "includeRawPdf=true for base64). The attachment must belong to ticketNoteId.",
        READ,
        Req("ticketNoteId", int, "Ticket note ID the attachment belongs to."),
        Req("attachmentId", int, "Attachment ID."),
        INCLUDE_DATA,
        MAX_INLINE,
        INCLUDE_RAW_PDF,
        MAX_TEXT,
    )
    async def get_ticket_note_attachment(c: AutotaskClient, a: Args) -> Any:
        return await _attachment(
            c, "TicketNoteAttachments", "TicketNotes", "ticketNoteID", a.ticketNoteId, a.attachmentId, a
        )

    @t(
        "autotask_search_ticket_note_attachments",
        "List the attachments of one ticket note. Useful when a note has an empty description and its content is "
        "a pasted image or file.",
        READ,
        Req("ticketNoteId", int, "Ticket note ID."),
        PAGE_SIZE,
    )
    async def search_ticket_note_attachments(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "TicketNoteAttachments", build(("eq", "parentID", a.ticketNoteId)), a, drop={"data"})

    @t(
        "autotask_create_ticket_attachment",
        "Upload a file to a ticket. Pass the content base64-encoded in data; the decoded size must be at most 3 MB "
        "(Autotask limit), which is checked before calling the API.",
        CREATE,
        Req("ticketId", int, "Ticket ID."),
        Req("title", str, "Attachment title, usually the file name (e.g. screenshot.png)."),
        Req("data", str, "Base64-encoded file content."),
        Opt("fullPath", str, "Original file name (defaults to title)."),
        Opt("contentType", str, "MIME type, e.g. image/png."),
        Opt("publish", int, "1 = all Autotask users (default), 2 = internal users only."),
    )
    async def create_ticket_attachment(c: AutotaskClient, a: Args) -> Any:
        data = "".join((a.data or "").split())
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolInputError("data is not valid base64.") from exc
        if not raw:
            raise ToolInputError("data is empty.")
        if len(raw) > MAX_UPLOAD_BYTES:
            raise ToolInputError(f"File is {len(raw)} bytes; Autotask accepts at most {MAX_UPLOAD_BYTES} bytes.")
        body = {
            "parentID": a.ticketId,
            "attachmentType": "FILE_ATTACHMENT",
            "title": a.title,
            "fullPath": a.fullPath or a.title,
            "data": data,
            "publish": a.get("publish", 1),
            **a.fields(["contentType"]),
        }
        # Attachments are created through the parent ticket URL (documented route); top-level as fallback.
        payload = await c.first_route("POST", [f"/Tickets/{a.ticketId}/Attachments", "/TicketAttachments"], body)
        return {"id": item_id(payload), "created": True, "entity": "TicketAttachments", "sizeBytes": len(raw)}
