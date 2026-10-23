# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Discovery and dispatch tools.

All tools are always listed in ``tools/list``. These helpers exist for agents that prefer to browse
by category or call tools indirectly. They are stateless: categories are a fixed map, dispatch
calls the named tool in the same request, and the router is keyword based.
"""

import re
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .. import _json
from ..config import Settings
from ._common import DESTRUCTIVE, READ, Args, Opt, Req, ToolInputError, tool

META_TOOLS = {
    "autotask_list_categories",
    "autotask_list_category_tools",
    "autotask_execute_tool",
    "autotask_router",
}

CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "companies": (
        "Companies, company notes and site configuration",
        [
            "autotask_search_companies", "autotask_create_company", "autotask_update_company",
            "autotask_get_company_site_configuration", "autotask_update_company_site_configuration",
            "autotask_get_company_note", "autotask_search_company_notes", "autotask_create_company_note",
        ],
    ),
    "contacts": (
        "Contacts at client companies",
        ["autotask_search_contacts", "autotask_create_contact", "autotask_update_contact"],
    ),
    "tickets": (
        "Tickets, ticket notes, checklists, charges, history and attachments",
        [
            "autotask_search_tickets", "autotask_get_ticket_details", "autotask_create_ticket",
            "autotask_update_ticket", "autotask_assign_least_loaded_resource", "autotask_get_ticket_note",
            "autotask_search_ticket_notes", "autotask_create_ticket_note", "autotask_search_ticket_checklist_items",
            "autotask_create_ticket_checklist_item", "autotask_update_ticket_checklist_item",
            "autotask_delete_ticket_checklist_item", "autotask_get_ticket_charge", "autotask_search_ticket_charges",
            "autotask_create_ticket_charge", "autotask_update_ticket_charge", "autotask_delete_ticket_charge",
            "autotask_get_ticket_history", "autotask_search_ticket_history", "autotask_get_ticket_attachment",
            "autotask_search_ticket_attachments", "autotask_get_ticket_note_attachment",
            "autotask_search_ticket_note_attachments", "autotask_create_ticket_attachment",
        ],
    ),
    "time_entries": (
        "Resources, roles and time entries",
        [
            "autotask_search_resources", "autotask_search_resource_roles", "autotask_create_time_entry",
            "autotask_search_time_entries",
        ],
    ),
    "projects": (
        "Projects, project notes, tasks and phases",
        [
            "autotask_search_projects", "autotask_create_project", "autotask_update_project",
            "autotask_get_project_note", "autotask_search_project_notes", "autotask_create_project_note",
            "autotask_search_tasks", "autotask_create_task", "autotask_list_phases", "autotask_create_phase",
        ],
    ),
    "sales": (
        "Opportunities, quotes, quote items and the product / service catalog",
        [
            "autotask_get_opportunity", "autotask_search_opportunities", "autotask_create_opportunity",
            "autotask_get_quote", "autotask_search_quotes", "autotask_create_quote", "autotask_get_quote_item",
            "autotask_search_quote_items", "autotask_create_quote_item", "autotask_update_quote_item",
            "autotask_delete_quote_item", "autotask_get_product", "autotask_search_products",
            "autotask_get_service", "autotask_search_services", "autotask_get_service_bundle",
            "autotask_search_service_bundles",
        ],
    ),
    "contracts": (
        "Contracts, service lines, billed units and recurring revenue",
        [
            "autotask_search_contracts", "autotask_get_contract", "autotask_list_expiring_contracts",
            "autotask_search_contract_services", "autotask_search_contract_service_units",
            "autotask_search_contract_service_bundles", "autotask_search_contract_service_bundle_units",
            "autotask_get_contract_recurring_lines", "autotask_create_contract", "autotask_create_contracts_bulk",
            "autotask_update_contract", "autotask_create_contract_service", "autotask_update_contract_service",
        ],
    ),
    "financial": (
        "Invoices, billing items, approval levels, billing codes and expenses",
        [
            "autotask_search_invoices", "autotask_get_invoice_details", "autotask_search_billing_items",
            "autotask_get_billing_item", "autotask_search_billing_item_approval_levels",
            "autotask_search_billing_codes", "autotask_get_expense_report", "autotask_search_expense_reports",
            "autotask_create_expense_report", "autotask_create_expense_item",
        ],
    ),
    "service_calls": (
        "Service calls, their tickets and technician assignments",
        [
            "autotask_get_service_call", "autotask_search_service_calls", "autotask_create_service_call",
            "autotask_update_service_call", "autotask_delete_service_call", "autotask_search_service_call_tickets",
            "autotask_create_service_call_ticket", "autotask_delete_service_call_ticket",
            "autotask_search_service_call_ticket_resources", "autotask_create_service_call_ticket_resource",
            "autotask_delete_service_call_ticket_resource",
        ],
    ),
    "configuration_items": ("Configuration items (devices and assets)", ["autotask_search_configuration_items"]),
    "reference": (
        "Picklists and field metadata, connection test and raw requests",
        [
            "autotask_list_queues", "autotask_list_ticket_statuses", "autotask_list_ticket_priorities",
            "autotask_get_field_info", "autotask_test_connection", "autotask_raw_request",
        ],
    ),
}  # fmt: skip

CATEGORY_ALIASES = {
    "time": "time_entries",
    "finance": "financial",
    "billing": "financial",
    "configuration": "configuration_items",
}

# (pattern, tool, why). The first matching rules win; order matters.
ROUTES: list[tuple[str, str, str]] = [
    (r"\b(log|record|add)\b.*\b(hours?|time)\b|\btime entr", "autotask_create_time_entry", "Log time"),
    (r"\btime (sheet|entries)\b|\bhours (worked|logged)\b", "autotask_search_time_entries", "Find time entries"),
    (r"\b(note|comment)\b.*\bticket\b|\bticket\b.*\b(note|comment)\b", "autotask_create_ticket_note", "Ticket note"),
    (r"\bassign\b.*\b(least|load|balance|fewest)\b", "autotask_assign_least_loaded_resource", "Load-balanced assign"),
    (r"\b(create|open|new|raise)\b.*\bticket\b", "autotask_create_ticket", "Create a ticket"),
    (r"\b(update|change|close|reassign|move)\b.*\bticket\b", "autotask_update_ticket", "Update a ticket"),
    (r"\bticket\b.*\b(history|audit)\b|\b(history|audit)\b.*\bticket\b", "autotask_search_ticket_history", "History"),
    (r"\bticket #?\d+\b|\bT\d{8}\.\d+\b", "autotask_get_ticket_details", "One ticket"),
    (r"\btickets?\b", "autotask_search_tickets", "Search tickets"),
    (r"\bwork ?types?\b|\bbilling codes?\b", "autotask_search_billing_codes", "Work types are billing codes"),
    (r"\bqueues?\b", "autotask_list_queues", "List queues"),
    (r"\bstatus(es)?\b", "autotask_list_ticket_statuses", "List ticket statuses"),
    (r"\bpriorit", "autotask_list_ticket_priorities", "List ticket priorities"),
    (r"\bpicklist|\bfield (info|values)\b", "autotask_get_field_info", "Field and picklist metadata"),
    (r"\b(create|add|new)\b.*\bcontact\b", "autotask_create_contact", "Create a contact"),
    (r"\bcontacts?\b|\bpeople\b", "autotask_search_contacts", "Search contacts"),
    (r"\bexpir", "autotask_list_expiring_contracts", "Expiring contracts"),
    (r"\bmrr\b|\brecurring\b", "autotask_get_contract_recurring_lines", "Recurring revenue"),
    (r"\bcontracts?\b", "autotask_search_contracts", "Search contracts"),
    (r"\b(create|new)\b.*\bquote\b", "autotask_create_quote", "Create a quote"),
    (r"\bquotes?\b", "autotask_search_quotes", "Search quotes"),
    (r"\bopportunit", "autotask_search_opportunities", "Search opportunities"),
    (r"\binvoices?\b", "autotask_search_invoices", "Search invoices"),
    (r"\bbilling items?\b|\bnot (yet )?invoiced\b", "autotask_search_billing_items", "Billing items"),
    (r"\bexpenses?\b", "autotask_search_expense_reports", "Expense reports"),
    (r"\bproducts?\b", "autotask_search_products", "Products"),
    (r"\bservice calls?\b", "autotask_search_service_calls", "Service calls"),
    (r"\bservices?\b", "autotask_search_services", "Services"),
    (r"\btasks?\b", "autotask_search_tasks", "Project tasks"),
    (r"\bprojects?\b", "autotask_search_projects", "Search projects"),
    (r"\broles?\b", "autotask_search_resource_roles", "Resource roles"),
    (r"\b(resources?|technicians?|users?|staff)\b", "autotask_search_resources", "Search resources"),
    (r"\b(devices?|assets?|configuration items?|computers?|servers?)\b", "autotask_search_configuration_items", "CIs"),
    (r"\b(companies|company|clients?|customers?|accounts?)\b", "autotask_search_companies", "Search companies"),
    (r"\b(connection|connect|test|health)\b", "autotask_test_connection", "Check the connection"),
]


def _guess_arguments(tool_name: str, intent: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    numbers = [int(n) for n in re.findall(r"#?(\d{3,})", intent)]
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hrs?|hours?)\b", intent, re.I)
    date = re.search(r"\b(20\d\d-\d\d-\d\d)\b", intent)
    if tool_name == "autotask_create_time_entry":
        if hours:
            args["hoursWorked"] = float(hours.group(1))
        if numbers and "ticket" in intent.lower():
            args["ticketID"] = numbers[0]
        if date:
            args["dateWorked"] = date.group(1)
    elif tool_name in ("autotask_get_ticket_details", "autotask_search_ticket_history", "autotask_create_ticket_note"):
        if numbers:
            args["ticketID" if tool_name == "autotask_get_ticket_details" else "ticketId"] = numbers[0]
    elif tool_name == "autotask_search_tickets":
        number = re.search(r"\bT\d{8}\.\d+\b", intent)
        if number:
            args["searchTerm"] = number.group(0)
        if date:
            args["createdAfter"] = date.group(1)
        if re.search(r"\bunassigned\b", intent, re.I):
            args["unassigned"] = True
    elif tool_name == "autotask_list_expiring_contracts":
        days = re.search(r"(\d+)\s*days?", intent, re.I)
        if days:
            args["daysAhead"] = int(days.group(1))
    for_name = re.search(r"\b(?:for|named|called)\s+([A-Z][\w&.\- ]{1,60})", intent)
    if for_name and tool_name in _SEARCH_TERM_TOOLS and "searchTerm" not in args:
        args["searchTerm"] = for_name.group(1).strip()
    return args


_SEARCH_TERM_TOOLS = {
    "autotask_search_companies", "autotask_search_contacts", "autotask_search_projects", "autotask_search_tasks",
    "autotask_search_contracts", "autotask_search_quotes", "autotask_search_opportunities",
    "autotask_search_products", "autotask_search_services", "autotask_search_resources",
    "autotask_search_configuration_items",
}  # fmt: skip


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, local=True, **k)

    @t(
        "autotask_list_categories",
        "List the tool categories (tickets, companies, financial, ...) with a short description and tool count. "
        "All tools are callable directly; this is only a guide.",
        READ,
    )
    async def list_categories(_: Any, a: Args) -> Any:
        return {
            "categories": [
                {"name": name, "description": desc, "toolCount": len(tools)}
                for name, (desc, tools) in CATEGORIES.items()
            ]
        }

    @t(
        "autotask_list_category_tools",
        "List the tools in one category with their full input schemas. Use after autotask_list_categories.",
        READ,
        Req("category", str, "Category name from autotask_list_categories, e.g. tickets, financial, companies."),
    )
    async def list_category_tools(_: Any, a: Args) -> Any:
        key = (a.category or "").strip().lower().replace(" ", "_")
        key = CATEGORY_ALIASES.get(key, key)
        if key not in CATEGORIES:
            raise ToolInputError(f"Unknown category {a.category!r}. Categories: {', '.join(CATEGORIES)}.")
        wanted = CATEGORIES[key][1]
        listed = {t.name: t for t in await mcp.list_tools()}
        return {
            "category": key,
            "tools": [
                {"name": n, "description": listed[n].description, "inputSchema": listed[n].inputSchema}
                for n in wanted
                if n in listed
            ],
        }

    @t(
        "autotask_execute_tool",
        "Call any Autotask tool by name with an arguments object. Use after autotask_list_category_tools.",
        DESTRUCTIVE,  # it can dispatch to any tool, including deletes
        Req("toolName", str, "Tool to call, e.g. autotask_search_tickets."),
        Opt("arguments", dict[str, Any], "Arguments for that tool."),
    )
    async def execute_tool(_: Any, a: Args) -> Any:
        name = (a.toolName or "").strip()
        if name in META_TOOLS:
            raise ToolInputError("execute_tool cannot call the discovery tools; call them directly.")
        if not any(t.name == name for t in await mcp.list_tools()):
            raise ToolInputError(f"Unknown tool {name!r}. Use autotask_list_categories to browse tools.")
        try:
            result = await mcp.call_tool(name, dict(a.arguments or {}))
        except ToolError as exc:
            return _json.error("invalid_argument", f"Invalid arguments for {name}: {exc}"[:1000])
        blocks = result[0] if isinstance(result, tuple) else result
        texts = [getattr(b, "text", "") for b in blocks if getattr(b, "text", None) is not None]
        return texts[0] if texts else _json.compact({"result": None})

    @t(
        "autotask_router",
        "Describe what you want to do in plain words and get the best matching tool(s) with any arguments that "
        "could be read from the text. Use it when unsure which tool to call.",
        READ,
        Req("intent", str, "What you want to do, e.g. 'find tickets for Acme Corp' or 'log 2 hours on ticket 12345'."),
    )
    async def router(_: Any, a: Args) -> Any:
        text = (a.intent or "").strip()
        if not text:
            raise ToolInputError("intent is empty.")
        suggestions = []
        for pattern, name, why in ROUTES:
            if re.search(pattern, text, re.I) and all(s["tool"] != name for s in suggestions):
                suggestions.append({"tool": name, "reason": why, "arguments": _guess_arguments(name, text)})
            if len(suggestions) == 3:
                break
        if not suggestions:
            return {
                "suggestions": [],
                "note": "No match. Browse with autotask_list_categories, or use autotask_raw_request.",
            }
        return {
            "suggestions": suggestions,
            "note": "Check the suggested tool's schema (autotask_list_category_tools) before calling it.",
        }
