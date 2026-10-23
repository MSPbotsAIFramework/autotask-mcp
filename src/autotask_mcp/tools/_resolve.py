# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Name-to-ID resolution shared by several tool modules (resources, roles, billing codes)."""

from typing import Any

from ..api import AutotaskClient, eq, op
from ._common import ToolInputError


def resource_label(r: dict[str, Any]) -> str:
    return f"{r.get('firstName', '')} {r.get('lastName', '')}".strip() or str(r.get("userName") or r.get("id"))


async def resource_id_by_name(c: AutotaskClient, name: str) -> int:
    """Resolve a resource (user) name to exactly one active resource ID."""
    text = " ".join(name.split())
    if not text:
        raise ToolInputError("resourceName is empty.")
    fields = ["id", "firstName", "lastName", "userName", "email", "isActive"]
    parts = text.split(" ")
    if len(parts) >= 2:
        filters = [eq("firstName", parts[0]), eq("lastName", " ".join(parts[1:]))]
    else:
        filters = [
            {
                "op": "or",
                "items": [eq("firstName", text), eq("lastName", text), eq("userName", text), eq("email", text)],
            }
        ]
    matches = await c.query("Resources", [*filters, eq("isActive", True)], 20, fields)
    if not matches and len(parts) >= 2:
        loose = [op("beginsWith", "firstName", parts[0]), op("beginsWith", "lastName", parts[-1])]
        matches = await c.query("Resources", [*loose, eq("isActive", True)], 20, fields)
    if len(matches) == 1:
        return int(matches[0]["id"])
    if not matches:
        raise ToolInputError(f"No active resource named {name!r}. Use autotask_search_resources to find the ID.")
    names = ", ".join(f"{resource_label(r)} (id {r['id']})" for r in matches[:10])
    raise ToolInputError(f"Several resources match {name!r}: {names}. Pass the resource ID instead.")


async def resource_roles(c: AutotaskClient, resource_id: int, include_inactive: bool = False) -> list[dict[str, Any]]:
    """Role assignments of a resource joined with role names."""
    filters = [eq("resourceID", resource_id)]
    if not include_inactive:
        filters.append(eq("isActive", True))
    links = await c.query("ResourceRoles", filters, 200)
    role_ids = sorted({int(link["roleID"]) for link in links if link.get("roleID") is not None})
    names: dict[int, dict[str, Any]] = {}
    if role_ids:
        roles = await c.query("Roles", [op("in", "id", role_ids)], 200, ["id", "name", "isActive"])
        names = {int(r["id"]): r for r in roles}
    out = []
    for link in links:
        rid = link.get("roleID")
        if rid is None:
            continue
        role = names.get(int(rid), {})
        out.append(
            {
                "roleID": int(rid),
                "roleName": role.get("name"),
                "isActive": link.get("isActive"),
                "roleIsActive": role.get("isActive"),
                "queueID": link.get("queueID"),
                "departmentID": link.get("departmentID"),
                "resourceRoleID": link.get("id"),
            }
        )
    return out


async def role_for(
    c: AutotaskClient,
    resource_id: int,
    role_id: int | None = None,
    role_name: str | None = None,
    parent_role_id: int | None = None,
) -> int:
    """Pick the role to use for ``resource_id``.

    Order: explicit role ID; role name (must match one active role); the parent ticket/task's
    role when it belongs to the same resource; the resource's only active role.
    """
    if role_id:
        return int(role_id)
    roles = [r for r in await resource_roles(c, resource_id) if r.get("roleIsActive") is not False]
    unique = {r["roleID"]: r for r in roles}
    if role_name:
        wanted = role_name.strip().lower()
        hits = [r for r in unique.values() if str(r.get("roleName") or "").lower() == wanted]
        if len(hits) == 1:
            return hits[0]["roleID"]
        listing = ", ".join(f"{r['roleName']} ({r['roleID']})" for r in unique.values()) or "none"
        raise ToolInputError(f"Resource {resource_id} has no single active role named {role_name!r}. Roles: {listing}.")
    if parent_role_id and int(parent_role_id) in unique:
        return int(parent_role_id)
    if len(unique) == 1:
        return next(iter(unique))
    if not unique:
        raise ToolInputError(f"Resource {resource_id} has no active roles; a role ID is required.")
    listing = ", ".join(f"{r['roleName']} ({r['roleID']})" for r in unique.values())
    raise ToolInputError(f"Resource {resource_id} has several active roles: {listing}. Pass the role ID or role name.")
