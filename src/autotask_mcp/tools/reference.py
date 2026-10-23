# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Reference data (queues, statuses, priorities, field and picklist metadata) and the raw request escape hatch."""

import json
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import _json
from ..api import ApiError, AutotaskClient
from ..config import Settings
from ._common import DESTRUCTIVE, READ, Args, Opt, Req, ToolInputError, tool

ENTITY_ALIASES = {"projecttasks": "Tasks", "tasks": "Tasks"}
ENTITY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,63}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./]*$")
FIELD_KEYS = (
    "name", "label", "dataType", "length", "isRequired", "isReadOnly", "isQueryable", "isReference",
    "referenceEntityType", "isPickList", "picklistParentValueField", "isSupportedWebhookField",
)  # fmt: skip
METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


def _entity(name: str) -> str:
    text = (name or "").strip()
    if not ENTITY_RE.match(text):
        raise ToolInputError("entityType must be an Autotask entity name such as Tickets or Companies.")
    return ENTITY_ALIASES.get(text.lower(), text)


def _field(f: dict[str, Any], with_values: bool) -> dict[str, Any]:
    out = {k: f[k] for k in FIELD_KEYS if f.get(k) not in (None, "", False)}
    values = f.get("picklistValues") or []
    if f.get("isPickList"):
        active = [
            {k: v.get(k) for k in ("value", "label", "parentValue", "isDefaultValue") if v.get(k) not in (None, "")}
            for v in values
            if v.get("isActive", True)
        ]
        if with_values:
            out["picklistValues"] = active
        out["picklistValueCount"] = len(active)
    if f.get("isReference"):
        ref = str(f.get("referenceEntityType") or "")
        if ref.lower().startswith("billingcode"):
            out["note"] = "Reference to BillingCodes, not a picklist: use autotask_search_billing_codes."
        else:
            out["note"] = f"Reference to {ref}, not a picklist: query that entity for valid IDs."
    return out


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    def ticket_picklist(name: str, field: str, label: str) -> None:
        @t(
            name,
            f"List the active ticket {label} with their IDs (from the Tickets {field} picklist). Use the IDs to "
            "filter, create or update tickets.",
            READ,
        )
        async def handler(c: AutotaskClient, a: Args) -> Any:
            values = await c.picklist("Tickets", field)
            return {"items": values, "count": len(values)}

    ticket_picklist("autotask_list_queues", "queueID", "queues")
    ticket_picklist("autotask_list_ticket_statuses", "status", "statuses")
    ticket_picklist("autotask_list_ticket_priorities", "priority", "priorities")

    @t(
        "autotask_get_field_info",
        "Get the field definitions of an Autotask entity, including picklist values. Pass fieldName for one field "
        "(also searched in custom fields). Reference fields such as the ticket Work Type (billingCodeID) are not "
        "picklists; use autotask_search_billing_codes for those.",
        READ,
        Req("entityType", str, "Entity name, e.g. Tickets, Companies, Contacts, Projects, Tasks, TicketNotes."),
        Opt("fieldName", str, "Only this field (case-insensitive)."),
    )
    async def get_field_info(c: AutotaskClient, a: Args) -> Any:
        entity = _entity(a.entityType)
        payload = await c.get(f"/{entity}/entityInformation/fields")
        fields = (payload or {}).get("fields") or []
        if a.fieldName:
            wanted = a.fieldName.strip().lower()
            hits = [_field(f, True) for f in fields if str(f.get("name", "")).lower() == wanted]
            if hits:
                return {"entityType": entity, "fields": hits}
            try:
                udf_payload = await c.get(f"/{entity}/entityInformation/userDefinedFields")
            except ApiError:
                udf_payload = None
            udfs = [
                _field(f, True)
                for f in (udf_payload or {}).get("fields") or []
                if str(f.get("name", "")).lower() == wanted
            ]
            if udfs:
                return {"entityType": entity, "userDefinedFields": udfs}
            raise ApiError("not_found", f"{entity} has no field named {a.fieldName}.", False, 404)
        result = {"entityType": entity, "fields": [_field(f, True) for f in fields], "count": len(fields)}
        if len(_json.compact(result)) > _json.MAX_CHARS:
            result["fields"] = [_field(f, False) for f in fields]
            result["note"] = "Picklist values left out to fit the size limit; call again with fieldName."
        return result

    @t(
        "autotask_raw_request",
        "Escape hatch for Autotask REST endpoints without a dedicated tool; prefer the typed tools. Authentication "
        "headers are added automatically and path is relative to the zone REST base (.../ATServicesRest/v1.0), "
        "e.g. /Companies/175 or /Companies/query. queryParams is a flat object of query string values.",
        DESTRUCTIVE,
        Req("method", str, "HTTP method: GET, POST, PATCH, PUT or DELETE."),
        Req("path", str, "Path under the REST v1.0 base, starting with /."),
        Opt("body", dict[str, Any], "JSON body for POST, PATCH or PUT."),
        Opt("queryParams", dict[str, Any], "Flat query parameters, e.g. {search: ...}."),
        title="Raw Autotask REST request",
    )
    async def raw_request(c: AutotaskClient, a: Args) -> Any:
        method = (a.method or "").strip().upper()
        if method not in METHODS:
            raise ToolInputError(f"method must be one of {', '.join(sorted(METHODS))}.")
        path = (a.path or "").strip()
        if re.match(r"(?i)^/?(atservicesrest/)?v1\.0(/|$)", path.lstrip("/")):
            path = "/" + re.sub(r"(?i)^/?(atservicesrest/)?v1\.0", "", path.lstrip("/")).lstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        if not PATH_RE.match(path) or ".." in path or "//" in path:
            raise ToolInputError("path must be a relative API path such as /Companies/175 (no scheme, host or '..').")
        params = {}
        for key, value in (a.queryParams or {}).items():
            if isinstance(value, dict | list):
                value = json.dumps(value, separators=(",", ":"))
            params[str(key)] = value
        body = a.body if method in ("POST", "PATCH", "PUT") else None
        result = await c.request(method, path, params=params, body=body)
        return result if result is not None else {"status": "ok"}
