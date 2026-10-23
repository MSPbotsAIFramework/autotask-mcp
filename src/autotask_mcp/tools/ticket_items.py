# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Records that hang off a ticket: notes, checklist items, charges and the audit history."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, build, clean
from ..config import Settings
from ._common import (
    CREATE,
    DELETE_WARNING,
    DESTRUCTIVE,
    PAGE_SIZE,
    READ,
    UPDATE,
    Args,
    Opt,
    Req,
    belongs,
    create,
    remove,
    require_any,
    search,
    title_from,
    tool,
    update,
    update_via_parent,
)


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    # ---- notes ----------------------------------------------------------

    @t(
        "autotask_get_ticket_note",
        "Get one ticket note by ticket ID and note ID.",
        READ,
        Req("ticketId", int, "Ticket ID."),
        Req("noteId", int, "Ticket note ID."),
    )
    async def get_ticket_note(c: AutotaskClient, a: Args) -> Any:
        return clean(belongs(await c.get_item("TicketNotes", a.noteId), "ticketID", a.ticketId, "Note"))

    @t(
        "autotask_search_ticket_notes",
        "List notes on one ticket. Scope the ticket list first: looping over many tickets uses up the API threshold.",
        READ,
        Req("ticketId", int, "Ticket ID."),
        PAGE_SIZE,
    )
    async def search_ticket_notes(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "TicketNotes", build(("eq", "ticketID", a.ticketId)), a)

    @t(
        "autotask_create_ticket_note",
        "Add a note to a ticket. noteType and publish are tenant picklists: read them with autotask_get_field_info "
        "(entityType TicketNotes) first. publish controls whether clients can see the note, so never guess it.",
        CREATE,
        Req("ticketId", int, "Ticket ID."),
        Opt("title", str, "Note title (defaults to the first line of the description)."),
        Req("description", str, "Note text."),
        Req("noteType", int, "Note type picklist ID."),
        Req("publish", int, "Publish (visibility) picklist ID."),
    )
    async def create_ticket_note(c: AutotaskClient, a: Args) -> Any:
        body = {
            "ticketID": a.ticketId,
            "title": a.title or title_from(a.description),
            "description": a.description,
            "noteType": a.noteType,
            "publish": a.publish,
        }
        return await create(c, "TicketNotes", body, f"/Tickets/{a.ticketId}/Notes")

    # ---- checklist ------------------------------------------------------

    @t(
        "autotask_search_ticket_checklist_items",
        "List the checklist items on a ticket with their completion status.",
        READ,
        Req("ticketId", int, "Ticket ID."),
    )
    async def search_checklist(c: AutotaskClient, a: Args) -> Any:
        rows = await c.query("TicketChecklistItems", build(("eq", "ticketID", a.ticketId)), 200)
        rows.sort(key=lambda r: (r.get("position") or 0, r.get("id") or 0))
        items = [clean(r) for r in rows]
        return {"items": items, "count": len(items)}

    @t(
        "autotask_create_ticket_checklist_item",
        "Add a checklist item to a ticket.",
        CREATE,
        Req("ticketId", int, "Ticket ID."),
        Req("itemName", str, "Checklist item text."),
        Opt("position", int, "Position in the list (1 = first)."),
        Opt("isCompleted", bool, "Create it already completed (default false)."),
    )
    async def create_checklist_item(c: AutotaskClient, a: Args) -> Any:
        body = {"ticketID": a.ticketId, "itemName": a.itemName, "isCompleted": a.get("isCompleted", False)}
        body.update(a.fields(["position"]))
        return await create(c, "TicketChecklistItems", body, f"/Tickets/{a.ticketId}/ChecklistItems")

    @t(
        "autotask_update_ticket_checklist_item",
        "Update a ticket checklist item: change its text, mark it complete or incomplete, or move it.",
        UPDATE,
        Req("ticketId", int, "Ticket ID."),
        Req("itemId", int, "Checklist item ID."),
        Opt("itemName", str, "New text."),
        Opt("isCompleted", bool, "Completed flag."),
        Opt("position", int, "New position."),
    )
    async def update_checklist_item(c: AutotaskClient, a: Args) -> Any:
        body = {"id": a.itemId, "ticketID": a.ticketId, **a.fields(["itemName", "isCompleted", "position"])}
        require_any({k: v for k, v in body.items() if k != "ticketID"})
        return await update(c, "TicketChecklistItems", body, f"/Tickets/{a.ticketId}/ChecklistItems")

    @t(
        "autotask_delete_ticket_checklist_item",
        f"Delete a checklist item from a ticket. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("ticketId", int, "Ticket ID."),
        Req("itemId", int, "Checklist item ID."),
        title="Delete ticket checklist item (irreversible)",
    )
    async def delete_checklist_item(c: AutotaskClient, a: Args) -> Any:
        paths = [f"/Tickets/{a.ticketId}/ChecklistItems/{a.itemId}", f"/TicketChecklistItems/{a.itemId}"]
        return await remove(c, paths, a.itemId, "TicketChecklistItems")

    # ---- charges --------------------------------------------------------

    @t(
        "autotask_get_ticket_charge",
        "Get one ticket charge (material, cost or expense line on a ticket) by ID.",
        READ,
        Req("chargeId", int, "Ticket charge ID."),
    )
    async def get_ticket_charge(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("TicketCharges", a.chargeId))

    @t(
        "autotask_search_ticket_charges",
        "List ticket charges (materials, costs, expenses). Pass ticketId; without it only a small page is returned.",
        READ,
        Opt("ticketId", int, "Ticket ID (recommended)."),
        Opt("pageSize", int, "Results per page (default 25, or 10 without ticketId; max 200)."),
    )
    async def search_ticket_charges(c: AutotaskClient, a: Args) -> Any:
        default = 25 if a.ticketId else 10
        return await search(c, "TicketCharges", build(("eq", "ticketID", a.ticketId)), a, default_size=default)

    @t(
        "autotask_create_ticket_charge",
        "Add a charge (materials, costs or expenses) to a ticket. chargeType is a picklist (autotask_get_field_info, "
        "entityType TicketCharges); billingCodeID comes from autotask_search_billing_codes.",
        CREATE,
        Req("ticketID", int, "Ticket ID."),
        Req("name", str, "Charge name."),
        Opt("description", str, "Description."),
        Req("chargeType", int, "Charge type picklist ID."),
        Opt("unitQuantity", float, "Quantity (default 1)."),
        Opt("unitPrice", float, "Price per unit."),
        Opt("unitCost", float, "Cost per unit."),
        Opt("datePurchased", str, "Date incurred (YYYY-MM-DD)."),
        Opt("productID", int, "Product ID."),
        Opt("billingCodeID", int, "Billing code ID."),
        Opt("billableToAccount", bool, "Billable to the client (default true)."),
        Opt("status", int, "Charge status picklist ID."),
    )
    async def create_ticket_charge(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            [
                "ticketID", "name", "description", "chargeType", "unitPrice", "unitCost", "datePurchased",
                "productID", "billingCodeID", "status",
            ]
        )  # fmt: skip
        body["unitQuantity"] = a.get("unitQuantity", 1)
        body["billableToAccount"] = a.get("billableToAccount", True)
        return await create(c, "TicketCharges", body, f"/Tickets/{a.ticketID}/Charges")

    @t(
        "autotask_update_ticket_charge",
        "Update a ticket charge. Only the fields you pass are changed.",
        UPDATE,
        Req("chargeId", int, "Ticket charge ID."),
        Opt("name", str, "Charge name."),
        Opt("description", str, "Description."),
        Opt("unitQuantity", float, "Quantity."),
        Opt("unitPrice", float, "Price per unit."),
        Opt("unitCost", float, "Cost per unit."),
        Opt("billableToAccount", bool, "Billable to the client."),
        Opt("status", int, "Charge status picklist ID."),
    )
    async def update_ticket_charge(c: AutotaskClient, a: Args) -> Any:
        fields = ["name", "description", "unitQuantity", "unitPrice", "unitCost", "billableToAccount", "status"]
        body = {"id": a.chargeId, **a.fields(fields)}
        require_any(body)

        async def parent() -> str:
            charge = await c.get_item("TicketCharges", a.chargeId)
            return f"/Tickets/{int(charge['ticketID'])}/Charges"

        return await update_via_parent(c, "TicketCharges", body, parent)

    @t(
        "autotask_delete_ticket_charge",
        f"Delete a ticket charge and its billing data. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("ticketId", int, "Ticket ID."),
        Req("chargeId", int, "Ticket charge ID."),
        title="Delete ticket charge (irreversible)",
    )
    async def delete_ticket_charge(c: AutotaskClient, a: Args) -> Any:
        paths = [f"/Tickets/{a.ticketId}/Charges/{a.chargeId}", f"/TicketCharges/{a.chargeId}"]
        return await remove(c, paths, a.chargeId, "TicketCharges")

    # ---- history --------------------------------------------------------

    @t(
        "autotask_get_ticket_history",
        "Get one ticket history entry by ID: one audited change to a ticket field (who, when, old and new value).",
        READ,
        Req("historyId", int, "Ticket history entry ID."),
    )
    async def get_ticket_history(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("TicketHistory", a.historyId))

    @t(
        "autotask_search_ticket_history",
        "Get the audit trail of a ticket (status changes, reassignments, priority edits, ...). Use it to answer "
        "when a ticket changed status or who changed a field. Entries are sorted by date.",
        READ,
        Req("ticketId", int, "Ticket ID."),
        Opt("pageSize", int, "Maximum entries (default 200, max 500)."),
    )
    async def search_ticket_history(c: AutotaskClient, a: Args) -> Any:
        # TicketHistory only accepts a single "ticketID eq" filter, so it is read in one call.
        size = min(max(int(a.get("pageSize", 200)), 1), 500)
        rows = await c.query("TicketHistory", build(("eq", "ticketID", a.ticketId)), size + 1)
        rows.sort(key=lambda r: (str(r.get("date") or ""), r.get("id") or 0))
        items = [clean(r) for r in rows[:size]]
        return {"items": items, "count": len(items), "has_more": len(rows) > size}
