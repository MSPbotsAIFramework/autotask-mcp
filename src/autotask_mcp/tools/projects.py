# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Projects, project notes, tasks and phases."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, build, clean
from ..config import Settings
from ._common import (
    CREATE,
    PAGE,
    PAGE_SIZE,
    READ,
    UPDATE,
    Args,
    Opt,
    Req,
    belongs,
    create,
    require_any,
    search,
    title_from,
    tool,
    update,
)
from ._resolve import role_for


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_search_projects",
        "Search projects by name, company, status or project lead. 25 per page by default; use page for more.",
        READ,
        Opt("searchTerm", str, "Text contained in the project name."),
        Opt("companyID", int, "Company ID."),
        Opt("status", int, "Project status picklist ID (e.g. 1 New, 2 In Progress, 5 Complete)."),
        Opt("projectLeadResourceID", int, "Project lead resource ID."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_projects(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("contains", "projectName", a.searchTerm),
            ("eq", "companyID", a.companyID),
            ("eq", "status", a.status),
            ("eq", "projectLeadResourceID", a.projectLeadResourceID),
        )
        return await search(c, "Projects", filters, a)

    @t(
        "autotask_create_project",
        "Create a project. Autotask requires company, name, status, type and start and end dates.",
        CREATE,
        Req("companyID", int, "Company ID."),
        Req("projectName", str, "Project name."),
        Opt("description", str, "Description."),
        Req("status", int, "Status picklist ID (e.g. 1 New, 2 In Progress, 5 Complete)."),
        Opt("startDate", str, "Start date (YYYY-MM-DD); sent as startDateTime."),
        Opt("endDate", str, "End date (YYYY-MM-DD); sent as endDateTime."),
        Opt("projectLeadResourceID", int, "Project manager resource ID."),
        Opt("estimatedHours", float, "Estimated hours; sent as estimatedTime."),
        Req("projectType", int, "Project type (2 Proposal, 3 Template, 4 Internal, 5 Client, 8 Baseline)."),
    )
    async def create_project(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {
                "companyID": "companyID",
                "projectName": "projectName",
                "description": "description",
                "status": "status",
                "startDate": "startDateTime",
                "endDate": "endDateTime",
                "projectLeadResourceID": "projectLeadResourceID",
                "estimatedHours": "estimatedTime",
                "projectType": "projectType",
            }
        )
        return await create(c, "Projects", body)

    @t(
        "autotask_update_project",
        "Update a project. Only the fields you pass are changed; e.g. status=5 marks it Complete.",
        UPDATE,
        Req("projectId", int, "Project ID."),
        Opt("projectName", str, "Project name."),
        Opt("description", str, "Description."),
        Opt("status", int, "Status picklist ID."),
        Opt("departmentID", int, "Department ID (sent as department)."),
        Opt("assignedResourceID", int, "Treated as projectLeadResourceID when that is not given."),
        Opt("assignedResourceRoleID", int, "Ignored: projects have no assigned role field."),
        Opt("projectLeadResourceID", int, "Project lead resource ID."),
        Opt("startDateTime", str, "Start date/time (ISO 8601)."),
        Opt("endDateTime", str, "End date/time (ISO 8601)."),
        Opt("estimatedTime", float, "Estimated hours."),
        Opt("userDefinedFields", list[dict[str, Any]], "Custom fields as a list of {name, value}."),
    )
    async def update_project(c: AutotaskClient, a: Args) -> Any:
        body = {
            "id": a.projectId,
            **a.fields(
                {
                    "projectName": "projectName",
                    "description": "description",
                    "status": "status",
                    "departmentID": "department",
                    "projectLeadResourceID": "projectLeadResourceID",
                    "startDateTime": "startDateTime",
                    "endDateTime": "endDateTime",
                    "estimatedTime": "estimatedTime",
                    "userDefinedFields": "userDefinedFields",
                }
            ),
        }
        if a.assignedResourceID is not None and a.projectLeadResourceID is None:
            body["projectLeadResourceID"] = a.assignedResourceID
        require_any(body)
        return await update(c, "Projects", body)

    # ---- notes ----------------------------------------------------------

    @t(
        "autotask_get_project_note",
        "Get one project note by project ID and note ID.",
        READ,
        Req("projectId", int, "Project ID."),
        Req("noteId", int, "Project note ID."),
    )
    async def get_project_note(c: AutotaskClient, a: Args) -> Any:
        return clean(belongs(await c.get_item("ProjectNotes", a.noteId), "projectID", a.projectId, "Note"))

    @t(
        "autotask_search_project_notes",
        "List notes on one project. Scope the project list first (status, company, dates): looping over many "
        "projects uses up the API threshold.",
        READ,
        Req("projectId", int, "Project ID."),
        PAGE_SIZE,
    )
    async def search_project_notes(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "ProjectNotes", build(("eq", "projectID", a.projectId)), a)

    @t(
        "autotask_create_project_note",
        "Add a note to a project. noteType and publish are tenant picklists (autotask_get_field_info, entityType "
        "ProjectNotes).",
        CREATE,
        Req("projectId", int, "Project ID."),
        Opt("title", str, "Note title (defaults to the first line of the description)."),
        Req("description", str, "Note text."),
        Opt("noteType", int, "Note type picklist ID."),
        Opt("publish", int, "Publish (visibility) picklist ID."),
        Opt("isAnnouncement", bool, "Show the note as a project announcement."),
    )
    async def create_project_note(c: AutotaskClient, a: Args) -> Any:
        body = {
            "projectID": a.projectId,
            "title": a.title or title_from(a.description),
            "description": a.description,
            **a.fields(["noteType", "publish", "isAnnouncement"]),
        }
        return await create(c, "ProjectNotes", body, f"/Projects/{a.projectId}/Notes")

    # ---- tasks ----------------------------------------------------------

    @t(
        "autotask_search_tasks",
        "Search project tasks by title, project, status or assignee. 25 per page by default; use page for more.",
        READ,
        Opt("searchTerm", str, "Text contained in the task title."),
        Opt("projectID", int, "Project ID."),
        Opt("status", int, "Task status picklist ID (e.g. 1 New, 2 In Progress, 5 Complete)."),
        Opt("assignedResourceID", int, "Assigned resource ID."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_tasks(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("contains", "title", a.searchTerm),
            ("eq", "projectID", a.projectID),
            ("eq", "status", a.status),
            ("eq", "assignedResourceID", a.assignedResourceID),
        )
        return await search(c, "Tasks", filters, a)

    @t(
        "autotask_create_task",
        "Create a task in a project. When assignedResourceID is given, the resource's only active role is used.",
        CREATE,
        Req("projectID", int, "Project ID."),
        Req("title", str, "Task title."),
        Opt("description", str, "Description."),
        Req("status", int, "Task status picklist ID (e.g. 1 New, 2 In Progress, 5 Complete)."),
        Opt("assignedResourceID", int, "Assigned resource ID."),
        Opt("estimatedHours", float, "Estimated hours."),
        Opt("taskType", int, "1 = fixed work (default), 2 = fixed duration."),
        Opt("startDateTime", str, "Start date/time (ISO 8601)."),
        Opt("endDateTime", str, "End date/time (ISO 8601)."),
    )
    async def create_task(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            [
                "projectID", "title", "description", "status", "assignedResourceID", "estimatedHours",
                "startDateTime", "endDateTime",
            ]
        )  # fmt: skip
        body["taskType"] = a.get("taskType", 1)
        if a.assignedResourceID:
            body["assignedResourceRoleID"] = await role_for(c, a.assignedResourceID)
        return await create(c, "Tasks", body, f"/Projects/{a.projectID}/Tasks")

    # ---- phases ---------------------------------------------------------

    @t(
        "autotask_list_phases",
        "List the phases of a project.",
        READ,
        Req("projectID", int, "Project ID."),
        PAGE_SIZE,
    )
    async def list_phases(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "Phases", build(("eq", "projectID", a.projectID)), a)

    @t(
        "autotask_create_phase",
        "Create a phase in a project.",
        CREATE,
        Req("projectID", int, "Project ID."),
        Req("title", str, "Phase title."),
        Opt("description", str, "Description."),
        Opt("startDate", str, "Start date (ISO)."),
        Opt("dueDate", str, "Due date (ISO)."),
        Opt("estimatedHours", float, "Estimated hours."),
    )
    async def create_phase(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(["projectID", "title", "description", "startDate", "dueDate", "estimatedHours"])
        return await create(c, "Phases", body, f"/Projects/{a.projectID}/Phases")
