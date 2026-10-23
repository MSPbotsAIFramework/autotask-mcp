# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Resources (users), their roles, and time entries."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, any_of, build, eq, item_id, op
from ..config import Settings
from ._common import CREATE, PAGE, PAGE_SIZE, READ, Args, Opt, Req, ToolInputError, search, tool
from ._resolve import resource_id_by_name, resource_roles, role_for

INTERNAL_TIME_USE_TYPE = 3  # BillingCodes.useType of internal (Regular Time) allocation codes


async def _internal_code(c: AutotaskClient, category: str) -> int:
    base = [eq("useType", INTERNAL_TIME_USE_TYPE), eq("isActive", True)]
    rows = await c.query("BillingCodes", [*base, eq("name", category.strip())], 10, ["id", "name"])
    if not rows:
        rows = await c.query("BillingCodes", [*base, op("contains", "name", category.strip())], 10, ["id", "name"])
    if len(rows) == 1:
        return int(rows[0]["id"])
    if rows:
        exact = [r for r in rows if str(r.get("name", "")).lower() == category.strip().lower()]
        if len(exact) == 1:
            return int(exact[0]["id"])
        names = ", ".join(str(r.get("name")) for r in rows)
        raise ToolInputError(f"Category {category!r} is ambiguous: {names}.")
    available = await c.query("BillingCodes", base, 50, ["id", "name"])
    names = ", ".join(sorted(str(r.get("name")) for r in available)) or "none"
    raise ToolInputError(f"No internal time category named {category!r}. Available: {names}.")


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_search_resources",
        "Search resources (Autotask users / technicians) by name, email or user name.",
        READ,
        Opt("searchTerm", str, "Text contained in the first name, last name, email or user name."),
        Opt("isActive", bool, "Only active (true) or inactive (false) resources."),
        Opt("resourceType", int, "Resource type picklist ID."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_resources(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "isActive", a.isActive), ("eq", "resourceType", a.resourceType))
        if a.searchTerm:
            term = a.searchTerm.strip()
            options = [op("contains", f, term) for f in ("firstName", "lastName", "email", "userName")]
            parts = term.split()
            if len(parts) >= 2:
                options.append(
                    {
                        "op": "and",
                        "items": [op("beginsWith", "firstName", parts[0]), op("beginsWith", "lastName", parts[-1])],
                    }
                )
            filters.append(any_of(*options))
        return await search(c, "Resources", filters, a)

    @t(
        "autotask_search_resource_roles",
        "List the roles a resource holds, with role names and IDs. Ticket assignments and ticket/task time entries "
        "need one of these role IDs. Give resourceId or resourceName; active roles only unless includeInactive.",
        READ,
        Opt("resourceId", int, "Resource ID."),
        Opt("resourceName", str, "Resource name, e.g. Jane Doe; used when resourceId is not given."),
        Opt("includeInactive", bool, "Also list inactive role assignments (default false)."),
    )
    async def search_resource_roles(c: AutotaskClient, a: Args) -> Any:
        if a.resourceId is None and not a.resourceName:
            raise ToolInputError("Give resourceId or resourceName.")
        rid = a.resourceId if a.resourceId is not None else await resource_id_by_name(c, a.resourceName)
        roles = await resource_roles(c, int(rid), bool(a.includeInactive))
        return {"resourceID": int(rid), "roles": roles, "count": len(roles)}

    @t(
        "autotask_create_time_entry",
        "Log time. With ticketID or taskID it is ticket/project time and needs a role (resolved automatically when "
        "unambiguous). Without both it is Regular Time and needs category, an internal time code name such as "
        "Internal Meeting or Training. summaryNotes may be an empty string.",
        CREATE,
        Opt("ticketID", int, "Ticket ID (omit for Regular Time)."),
        Opt("taskID", int, "Project task ID (omit for Regular Time)."),
        Opt("resourceID", int, "Resource logging the time. Can be omitted when resourceName is given."),
        Opt("resourceName", str, "Name of the resource logging the time, resolved to resourceID."),
        Opt(
            "roleID",
            int,
            "Role ID (one of the resource's active roles, see autotask_search_resource_roles). When omitted: the "
            "parent's role if the parent is assigned to this resource, else the resource's only active role.",
        ),
        Opt("roleName", str, "Role name instead of roleID (case-insensitive)."),
        Opt("category", str, "Internal time category name for Regular Time (required when no ticketID/taskID)."),
        Req("dateWorked", str, "Date worked (YYYY-MM-DD)."),
        Opt("startDateTime", str, "Start date/time (ISO 8601)."),
        Opt("endDateTime", str, "End date/time (ISO 8601)."),
        Req("hoursWorked", float, "Hours worked."),
        Req("summaryNotes", str, "Summary notes (may be empty)."),
        Opt("internalNotes", str, "Internal notes."),
    )
    async def create_time_entry(c: AutotaskClient, a: Args) -> Any:
        if a.ticketID is not None and a.taskID is not None:
            raise ToolInputError("Give ticketID or taskID, not both.")
        if a.resourceID is None and not a.resourceName:
            raise ToolInputError("Give resourceID or resourceName.")
        resource = a.resourceID if a.resourceID is not None else await resource_id_by_name(c, a.resourceName)
        body: dict[str, Any] = {
            "resourceID": int(resource),
            "dateWorked": a.dateWorked,
            "hoursWorked": a.hoursWorked,
            "summaryNotes": a.summaryNotes or "",
            **a.fields(["startDateTime", "endDateTime", "internalNotes"]),
        }
        if a.ticketID is not None or a.taskID is not None:
            entity, parent_id = ("Tickets", a.ticketID) if a.ticketID is not None else ("Tasks", a.taskID)
            parent_role = None
            if not a.roleID:
                parent = await c.get_item(entity, int(parent_id))
                if parent.get("assignedResourceID") == int(resource):
                    parent_role = parent.get("assignedResourceRoleID")
            body["roleID"] = await role_for(c, int(resource), a.roleID, a.roleName, parent_role)
            body["ticketID" if a.ticketID is not None else "taskID"] = int(parent_id)
        else:
            if not a.category:
                raise ToolInputError("Regular Time (no ticketID or taskID) needs a category.")
            body["billingCodeID"] = await _internal_code(c, a.category)
        payload = await c.post("/TimeEntries", body)
        return {"id": item_id(payload), "created": True, "entity": "TimeEntries", **_echo(body)}

    @t(
        "autotask_search_time_entries",
        "Search time entries by resource, ticket, task, date range, approval status or billable flag. "
        "approvalStatus=unapproved finds entries not yet approved and posted. Time entries have no project field: "
        "for project time, find the project's tasks with autotask_search_tasks and filter by taskId.",
        READ,
        Opt("resourceId", int, "Resource ID."),
        Opt("ticketId", int, "Ticket ID."),
        Opt("taskId", int, "Task ID."),
        Opt("approvalStatus", str, "unapproved, approved or all (default all)."),
        Opt("billable", bool, "true = billable only, false = non-billable only."),
        Opt("dateWorkedAfter", str, "Worked on or after this date (ISO, e.g. 2026-01-01)."),
        Opt("dateWorkedBefore", str, "Worked on or before this date (ISO)."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_time_entries(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "resourceID", a.resourceId),
            ("eq", "ticketID", a.ticketId),
            ("eq", "taskID", a.taskId),
            ("gte", "dateWorked", a.dateWorkedAfter),
            ("lte", "dateWorked", a.dateWorkedBefore),
        )
        status = (a.approvalStatus or "all").strip().lower()
        if status == "unapproved":
            filters.append(op("notExist", "billingApprovalDateTime"))
        elif status == "approved":
            filters.append(op("exist", "billingApprovalDateTime"))
        elif status != "all":
            raise ToolInputError("approvalStatus must be unapproved, approved or all.")
        if a.billable is not None:
            filters.append(eq("isNonBillable", not a.billable))
        return await search(c, "TimeEntries", filters, a)


def _echo(body: dict[str, Any]) -> dict[str, Any]:
    return {k: body[k] for k in ("resourceID", "roleID", "ticketID", "taskID", "billingCodeID") if k in body}
