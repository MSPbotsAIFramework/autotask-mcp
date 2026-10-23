# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tickets: search, details, create, update and least-loaded assignment."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import ApiError, AutotaskClient, any_of, build, clean, eq, item_id, op
from ..config import Settings
from ._common import (
    CREATE,
    PAGE,
    PAGE_SIZE,
    READ,
    UPDATE,
    Args,
    Opt,
    Param,
    Req,
    ToolInputError,
    require_any,
    search,
    tool,
    update,
)
from ._resolve import role_for

COMPLETE_STATUS = 5  # system status "Complete"

RESOURCE_HELP = (
    "Assigned resource ID. Autotask also needs that resource's role: pass assignedResourceRoleID or "
    "assignedResourceRoleName, or omit both to use the resource's only active role."
)
ROLE_ID_HELP = "Role ID of the assigned resource (see autotask_search_resource_roles). Resolved when omitted."
ROLE_NAME_HELP = "Role name of the assigned resource, e.g. Help Desk, used instead of assignedResourceRoleID."
QUEUE_HELP = "Queue ID (see autotask_list_queues)."
ISSUE_HELP = "Issue type picklist ID (autotask_get_field_info, entityType Tickets, fieldName issueType)."
SUB_ISSUE_HELP = "Sub-issue type picklist ID; must belong to the issueType."
WORK_TYPE_HELP = "Work type: a BillingCodes ID, not a picklist. Find it with autotask_search_billing_codes (useType 1)."
DUE_HELP = (
    "Due date and time, ISO 8601 (e.g. 2026-03-15T17:00:00Z). Required on new tickets unless the ticket "
    "category supplies a default."
)

# Plain ticket fields accepted by create (and by createTicket in assign_least_loaded_resource).
TICKET_CREATE_FIELDS = [
    "companyID", "title", "description", "status", "priority", "contactID", "queueID", "dueDateTime",
    "ticketCategory", "ticketType", "issueType", "subIssueType", "source", "billingCodeID",
    "serviceLevelAgreementID", "estimatedHours", "projectID", "resolution", "userDefinedFields",
    "assignedResourceID", "assignedResourceRoleID",
]  # fmt: skip


def ticket_create_params() -> list[Param]:
    return [
        Req("companyID", int, "Company ID."),
        Req("title", str, "Ticket title."),
        Req("description", str, "Ticket description."),
        Opt("status", int, "Status picklist ID (default 1, New). See autotask_list_ticket_statuses."),
        Opt("priority", int, "Priority picklist ID. See autotask_list_ticket_priorities."),
        Opt("assignedResourceID", int, RESOURCE_HELP),
        Opt("assignedResourceRoleID", int, ROLE_ID_HELP),
        Opt("assignedResourceRoleName", str, ROLE_NAME_HELP),
        Opt("contactID", int, "Primary contact ID."),
        Opt("queueID", int, QUEUE_HELP),
        Opt("dueDateTime", str, DUE_HELP),
        Opt("ticketCategory", int, "Ticket category picklist ID."),
        Opt("ticketType", int, "Ticket type picklist ID (e.g. Service Request, Incident, Problem, Change)."),
        Opt("issueType", int, ISSUE_HELP),
        Opt("subIssueType", int, SUB_ISSUE_HELP),
        Opt("source", int, "Source picklist ID (e.g. Phone, Email, Portal)."),
        Opt("billingCodeID", int, WORK_TYPE_HELP),
        Opt("serviceLevelAgreementID", int, "Service level agreement ID."),
        Opt("estimatedHours", float, "Estimated hours."),
        Opt("projectID", int, "Project ID to link the ticket to."),
        Opt("ticketAdditionalContacts", list[int], "Additional contact IDs to add to the ticket."),
        Opt("resolution", str, "Resolution text on the ticket itself (not a note)."),
        Opt("userDefinedFields", list[dict[str, Any]], "Custom fields as a list of {name, value}."),
    ]


async def create_ticket_record(c: AutotaskClient, values: dict[str, Any]) -> dict[str, Any]:
    """Create a ticket from tool-style values; resolves the role and adds additional contacts."""
    body = {k: values[k] for k in TICKET_CREATE_FIELDS if values.get(k) is not None}
    body.setdefault("status", 1)
    if body.get("assignedResourceID") and not body.get("assignedResourceRoleID"):
        body["assignedResourceRoleID"] = await role_for(
            c, int(body["assignedResourceID"]), role_name=values.get("assignedResourceRoleName")
        )
    payload = await c.post("/Tickets", body)
    ticket_id = item_id(payload)
    result: dict[str, Any] = {"id": ticket_id, "created": True, "entity": "Tickets"}
    if body.get("assignedResourceRoleID"):
        result["assignedResourceRoleID"] = body["assignedResourceRoleID"]
    extra = values.get("ticketAdditionalContacts") or []
    if extra and ticket_id is not None:
        result["additionalContacts"] = [await _add_contact(c, int(ticket_id), int(cid)) for cid in extra]
    return result


async def _add_contact(c: AutotaskClient, ticket_id: int, contact_id: int) -> dict[str, Any]:
    body = {"ticketID": ticket_id, "contactID": contact_id}
    try:
        await c.first_route(
            "POST",
            ["/TicketAdditionalContacts", f"/Tickets/{ticket_id}/AdditionalContacts"],
            body,
        )
        return {"contactID": contact_id, "added": True}
    except ApiError as exc:
        return {"contactID": contact_id, "added": False, "error": exc.message}


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_search_tickets",
        "Search tickets by company, contact, queue, status, priority, assignee or dates. Without status only open "
        "(not Complete) tickets are returned. Use autotask_get_ticket_details for one ticket's full data.",
        READ,
        Opt("searchTerm", str, "Ticket number prefix (e.g. T2026) or text contained in the title."),
        Opt("companyID", int, "Company ID."),
        Opt("contactID", int, "Primary contact ID."),
        Opt("status", int, "Status picklist ID. Omit for all open tickets."),
        Opt("priority", int, "Priority picklist ID (see autotask_list_ticket_priorities)."),
        Opt("queueID", int, QUEUE_HELP),
        Opt("assignedResourceID", int, "Assigned resource ID."),
        Opt("unassigned", bool, "true = only tickets with no assigned resource."),
        Opt("createdAfter", str, "Created on or after this date (ISO, e.g. 2026-01-01)."),
        Opt("createdBefore", str, "Created on or before this date (ISO)."),
        Opt("lastActivityAfter", str, "Last activity on or after this date (ISO)."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_tickets(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyID),
            ("eq", "contactID", a.contactID),
            ("eq", "priority", a.priority),
            ("eq", "queueID", a.queueID),
            ("eq", "assignedResourceID", a.assignedResourceID),
            ("gte", "createDate", a.createdAfter),
            ("lte", "createDate", a.createdBefore),
            ("gte", "lastActivityDate", a.lastActivityAfter),
        )
        filters.append(eq("status", a.status) if a.status is not None else op("noteq", "status", COMPLETE_STATUS))
        if a.unassigned:
            filters.append(op("notExist", "assignedResourceID"))
        if a.searchTerm:
            term = a.searchTerm.strip()
            filters.append(any_of(op("beginsWith", "ticketNumber", term), op("contains", "title", term)))
        return await search(c, "Tickets", filters, a)

    @t(
        "autotask_get_ticket_details",
        "Get one ticket by ID with all its fields and custom fields. With fullDetails=true the latest notes and "
        "time entries are included as well.",
        READ,
        Req("ticketID", int, "Ticket ID."),
        Opt("fullDetails", bool, "Also return recent notes and time entries (default false)."),
    )
    async def get_ticket_details(c: AutotaskClient, a: Args) -> Any:
        ticket = clean(await c.get_item("Tickets", a.ticketID))
        if not a.fullDetails:
            return ticket
        notes = await c.query("TicketNotes", [eq("ticketID", a.ticketID)], 200)
        notes.sort(key=lambda n: str(n.get("createDateTime") or ""), reverse=True)
        entries = await c.query("TimeEntries", [eq("ticketID", a.ticketID)], 200)
        entries.sort(key=lambda e: str(e.get("dateWorked") or ""), reverse=True)
        return {
            "ticket": ticket,
            "notes": [clean(n) for n in notes[:20]],
            "notesTotal": len(notes),
            "timeEntries": [clean(e) for e in entries[:20]],
            "timeEntriesTotal": len(entries),
            "hoursWorkedTotal": round(sum(float(e.get("hoursWorked") or 0) for e in entries), 2),
        }

    @t(
        "autotask_create_ticket",
        "Create a ticket. Needs a company, title and description; status defaults to New. Autotask usually also "
        "requires priority, a queue or assignee and dueDateTime. Work type is billingCodeID "
        "(autotask_search_billing_codes).",
        CREATE,
        *ticket_create_params(),
    )
    async def create_ticket(c: AutotaskClient, a: Args) -> Any:
        values = a.fields(TICKET_CREATE_FIELDS + ["assignedResourceRoleName", "ticketAdditionalContacts"])
        return await create_ticket_record(c, values)

    @t(
        "autotask_update_ticket",
        "Update a ticket. Only the fields you pass are changed. When reassigning across queues send queueID with "
        "assignedResourceID: Autotask refuses a resource that serves no queue on the ticket.",
        UPDATE,
        Req("ticketId", int, "Ticket ID."),
        Opt("title", str, "Title."),
        Opt("description", str, "Description."),
        Opt("status", int, "Status picklist ID (see autotask_list_ticket_statuses)."),
        Opt("priority", int, "Priority picklist ID (see autotask_list_ticket_priorities)."),
        Opt("assignedResourceID", int, RESOURCE_HELP),
        Opt("assignedResourceRoleID", int, ROLE_ID_HELP),
        Opt("assignedResourceRoleName", str, ROLE_NAME_HELP),
        Opt("dueDateTime", str, "Due date and time, ISO 8601."),
        Opt("contactID", int, "Primary contact ID."),
        Opt("queueID", int, QUEUE_HELP),
        Opt("issueType", int, ISSUE_HELP),
        Opt("subIssueType", int, SUB_ISSUE_HELP),
        Opt("billingCodeID", int, WORK_TYPE_HELP),
    )
    async def update_ticket(c: AutotaskClient, a: Args) -> Any:
        body: dict[str, Any] = {
            "id": a.ticketId,
            **a.fields(
                [
                    "title",
                    "description",
                    "status",
                    "priority",
                    "assignedResourceID",
                    "assignedResourceRoleID",
                    "dueDateTime",
                    "contactID",
                    "queueID",
                    "issueType",
                    "subIssueType",
                    "billingCodeID",
                ]
            ),  # fmt: skip
        }
        if a.assignedResourceRoleName and not a.assignedResourceRoleID:
            resource = a.assignedResourceID
            if resource is None:
                resource = (await c.get_item("Tickets", a.ticketId)).get("assignedResourceID")
                if resource is None:
                    raise ToolInputError("The ticket has no assigned resource; pass assignedResourceID.")
                body["assignedResourceID"] = int(resource)
            body["assignedResourceRoleID"] = await role_for(c, int(resource), role_name=a.assignedResourceRoleName)
        elif a.assignedResourceID and not a.assignedResourceRoleID:
            body["assignedResourceRoleID"] = await role_for(c, a.assignedResourceID)
        require_any(body)
        return await update(c, "Tickets", body)

    @t(
        "autotask_assign_least_loaded_resource",
        "Assign a ticket to whichever of the given technicians has the fewest tickets with the given status "
        "(optionally only in queueIDs). Give ticketID to reassign an existing ticket, or createTicket to create "
        "and assign in one call (then queueIDs must hold exactly one queue). Ties go to the earlier technician.",
        UPDATE,
        Req(
            "technicians",
            list[dict[str, Any]],
            "Candidates as a list of {resourceID, roleID}. Only these are considered; roleID is used as "
            "assignedResourceRoleID.",
        ),
        Req("status", int, "Ticket status ID whose tickets count toward each technician's load."),
        Opt("queueIDs", list[int], "Only tickets in these queues count. Exactly one entry when createTicket is used."),
        Opt("ticketID", int, "Existing ticket to reassign. Give this or createTicket."),
        Opt(
            "createTicket",
            dict[str, Any],
            "Fields of a new ticket, as for autotask_create_ticket (companyID, title, description required; "
            "assignedResourceID is computed). Give this or ticketID.",
        ),
    )
    async def assign_least_loaded(c: AutotaskClient, a: Args) -> Any:
        techs = _technicians(a.technicians)
        queues = [int(q) for q in (a.queueIDs or [])]
        if (a.ticketID is None) == (a.createTicket is None):
            raise ToolInputError("Give exactly one of ticketID or createTicket.")
        new_ticket = dict(a.createTicket or {})
        if a.createTicket is not None:
            missing = [k for k in ("companyID", "title", "description") if new_ticket.get(k) in (None, "")]
            if missing:
                raise ToolInputError(f"createTicket is missing: {', '.join(missing)}.")
            if len(queues) != 1:
                raise ToolInputError("queueIDs must contain exactly one queue when createTicket is used.")

        loads = []
        for tech in techs:
            filters = [eq("status", a.status), eq("assignedResourceID", tech["resourceID"])]
            if queues:
                filters.append(op("in", "queueID", queues))
            if a.ticketID is not None:
                filters.append(op("noteq", "id", a.ticketID))  # the ticket being moved does not count
            loads.append({**tech, "load": await c.count("Tickets", filters)})
        chosen = min(loads, key=lambda x: x["load"])  # min() keeps the first of equal loads

        if a.ticketID is not None:
            body = {
                "id": a.ticketID,
                "assignedResourceID": chosen["resourceID"],
                "assignedResourceRoleID": chosen["roleID"],
            }
            await c.patch("/Tickets", body)
            ticket_id, created = a.ticketID, False
        else:
            new_ticket.pop("assignedResourceID", None)
            new_ticket.update(
                {
                    "queueID": queues[0],
                    "assignedResourceID": chosen["resourceID"],
                    "assignedResourceRoleID": chosen["roleID"],
                }
            )
            new_ticket.setdefault("status", a.status)
            result = await create_ticket_record(c, new_ticket)
            ticket_id, created = result["id"], True
        return {
            "ticketID": ticket_id,
            "created": created,
            "assignedResourceID": chosen["resourceID"],
            "assignedResourceRoleID": chosen["roleID"],
            "loads": [{"resourceID": x["resourceID"], "load": x["load"]} for x in loads],
            "note": "Loads are counted at call time; concurrent calls are not serialized.",
        }


def _technicians(raw: Any) -> list[dict[str, int]]:
    techs = []
    for entry in raw or []:
        if not isinstance(entry, dict) or entry.get("resourceID") is None or entry.get("roleID") is None:
            raise ToolInputError("Each technician needs resourceID and roleID.")
        try:
            techs.append({"resourceID": int(entry["resourceID"]), "roleID": int(entry["roleID"])})
        except (TypeError, ValueError) as exc:
            raise ToolInputError("technician resourceID and roleID must be numbers.") from exc
    if not techs:
        raise ToolInputError("technicians must contain at least one entry.")
    return techs
