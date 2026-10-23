# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Service calls (scheduled work), the tickets on them and the resources assigned to those tickets."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import ApiError, AutotaskClient, build, clean
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
    create,
    remove,
    require_any,
    search,
    tool,
    update,
)


async def _delete_child(c: AutotaskClient, entity: str, record_id: int, parent_field: str, parent_url: str) -> Any:
    """DELETE ``/{entity}/{id}``; on 404/405 look up the parent and use the parent-scoped URL."""
    try:
        return await remove(c, [f"/{entity}/{record_id}"], record_id, entity)
    except ApiError as exc:
        if exc.status not in (404, 405):
            raise
    record = await c.get_item(entity, record_id)
    path = parent_url.format(parent=int(record[parent_field]), id=record_id)
    return await remove(c, [path], record_id, entity)


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_get_service_call",
        "Get one service call by ID.",
        READ,
        Req("serviceCallId", int, "Service call ID."),
    )
    async def get_service_call(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("ServiceCalls", a.serviceCallId))

    @t(
        "autotask_search_service_calls",
        "Search service calls by company, status or start date range.",
        READ,
        Opt("companyId", int, "Company ID."),
        Opt("status", int, "Status picklist ID."),
        Opt("startAfter", str, "Starts on or after (ISO 8601)."),
        Opt("startBefore", str, "Starts on or before (ISO 8601)."),
        PAGE_SIZE,
    )
    async def search_service_calls(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyId),
            ("eq", "status", a.status),
            ("gte", "startDateTime", a.startAfter),
            ("lte", "startDateTime", a.startBefore),
        )
        return await search(c, "ServiceCalls", filters, a)

    @t(
        "autotask_create_service_call",
        "Create a service call: a scheduled block of work. Link tickets with autotask_create_service_call_ticket.",
        CREATE,
        Req("description", str, "Description."),
        Opt("status", int, "Status picklist ID."),
        Req("startDateTime", str, "Start (ISO 8601)."),
        Req("endDateTime", str, "End (ISO 8601)."),
        Opt("companyID", int, "Company ID."),
        Opt("companyLocationID", int, "Company location ID."),
        Opt("complete", bool, "Mark the call complete."),
    )
    async def create_service_call(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {
                "description": "description",
                "status": "status",
                "startDateTime": "startDateTime",
                "endDateTime": "endDateTime",
                "companyID": "companyID",
                "companyLocationID": "companyLocationID",
                "complete": "isComplete",
            }
        )
        return await create(c, "ServiceCalls", body)

    @t(
        "autotask_update_service_call",
        "Update a service call: description, status or times. To close it set complete=true or change the status.",
        UPDATE,
        Req("serviceCallId", int, "Service call ID."),
        Opt("description", str, "Description."),
        Opt("status", int, "Status picklist ID."),
        Opt("startDateTime", str, "Start (ISO 8601)."),
        Opt("endDateTime", str, "End (ISO 8601)."),
        Opt("complete", bool, "Complete flag."),
    )
    async def update_service_call(c: AutotaskClient, a: Args) -> Any:
        body = {
            "id": a.serviceCallId,
            **a.fields(
                {
                    "description": "description",
                    "status": "status",
                    "startDateTime": "startDateTime",
                    "endDateTime": "endDateTime",
                    "complete": "isComplete",
                }
            ),
        }
        require_any(body)
        return await update(c, "ServiceCalls", body)

    @t(
        "autotask_delete_service_call",
        f"Delete a service call and its ticket links. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("serviceCallId", int, "Service call ID."),
        title="Delete service call (irreversible)",
    )
    async def delete_service_call(c: AutotaskClient, a: Args) -> Any:
        return await remove(c, [f"/ServiceCalls/{a.serviceCallId}"], a.serviceCallId, "ServiceCalls")

    # ---- tickets on a service call ---------------------------------------

    @t(
        "autotask_search_service_call_tickets",
        "Find ticket links on service calls: the tickets of a service call, or the service calls of a ticket.",
        READ,
        Opt("serviceCallId", int, "Service call ID."),
        Opt("ticketId", int, "Ticket ID."),
        PAGE_SIZE,
    )
    async def search_service_call_tickets(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "serviceCallID", a.serviceCallId), ("eq", "ticketID", a.ticketId))
        return await search(c, "ServiceCallTickets", filters, a)

    @t(
        "autotask_create_service_call_ticket",
        "Link a ticket to a service call.",
        CREATE,
        Req("serviceCallID", int, "Service call ID."),
        Req("ticketID", int, "Ticket ID."),
    )
    async def create_service_call_ticket(c: AutotaskClient, a: Args) -> Any:
        body = {"serviceCallID": a.serviceCallID, "ticketID": a.ticketID}
        return await create(c, "ServiceCallTickets", body, f"/ServiceCalls/{a.serviceCallID}/Tickets")

    @t(
        "autotask_delete_service_call_ticket",
        f"Remove a ticket link from a service call. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("serviceCallTicketId", int, "Service call ticket (link) ID."),
        title="Delete service call ticket association (irreversible)",
    )
    async def delete_service_call_ticket(c: AutotaskClient, a: Args) -> Any:
        return await _delete_child(
            c, "ServiceCallTickets", a.serviceCallTicketId, "serviceCallID", "/ServiceCalls/{parent}/Tickets/{id}"
        )

    # ---- resources on a service call ticket ------------------------------

    @t(
        "autotask_search_service_call_ticket_resources",
        "Find technician assignments on service call tickets.",
        READ,
        Opt("serviceCallTicketId", int, "Service call ticket (link) ID."),
        Opt("resourceId", int, "Resource ID."),
        PAGE_SIZE,
    )
    async def search_sct_resources(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "serviceCallTicketID", a.serviceCallTicketId), ("eq", "resourceID", a.resourceId))
        return await search(c, "ServiceCallTicketResources", filters, a)

    @t(
        "autotask_create_service_call_ticket_resource",
        "Assign a technician to a service call ticket.",
        CREATE,
        Req("serviceCallTicketID", int, "Service call ticket (link) ID."),
        Req("resourceID", int, "Resource ID."),
        Opt("roleID", int, "Role ID."),
    )
    async def create_sct_resource(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(["serviceCallTicketID", "resourceID", "roleID"])
        child = f"/ServiceCallTickets/{a.serviceCallTicketID}/Resources"
        return await create(c, "ServiceCallTicketResources", body, child)

    @t(
        "autotask_delete_service_call_ticket_resource",
        f"Remove a technician assignment from a service call ticket. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("serviceCallTicketResourceId", int, "Service call ticket resource ID."),
        title="Delete service call ticket resource assignment (irreversible)",
    )
    async def delete_sct_resource(c: AutotaskClient, a: Args) -> Any:
        return await _delete_child(
            c,
            "ServiceCallTicketResources",
            a.serviceCallTicketResourceId,
            "serviceCallTicketID",
            "/ServiceCallTickets/{parent}/Resources/{id}",
        )
