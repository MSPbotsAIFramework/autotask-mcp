# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""FastMCP server and HTTP app."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings
from .credentials import CredentialMiddleware
from .tools import (
    attachments,
    companies,
    contacts,
    contracts,
    finance,
    meta,
    projects,
    reference,
    sales,
    service_calls,
    ticket_items,
    tickets,
    time_entries,
)

INSTRUCTIONS = (
    "Autotask PSA is the ticketing, project, contract and billing system MSPs run their service desk on. "
    "Most records belong to a company, so start with autotask_search_companies to get the company ID. "
    "Typical flows: tickets -> autotask_search_tickets then autotask_get_ticket_details; new ticket -> "
    "autotask_list_queues / autotask_list_ticket_priorities, then autotask_create_ticket; log work -> "
    "autotask_create_time_entry (roles: autotask_search_resource_roles). Picklist values (status, priority, "
    "note type, publish, ...) differ per tenant: read them with autotask_get_field_info instead of guessing. "
    "A ticket's Work Type is billingCodeID, found with autotask_search_billing_codes (useType 1). "
    "Scope parent lists before looping over child records: Autotask limits API calls per hour. "
    "Ask the user before deleting anything."
)

MODULES = (
    companies,
    contacts,
    tickets,
    ticket_items,
    attachments,
    time_entries,
    projects,
    sales,
    contracts,
    finance,
    service_calls,
    reference,
    meta,
)


def create_mcp(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="autotask-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # The gateway forwards requests with its own Host header; DNS-rebinding
        # protection would reject them with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in MODULES:
        module.register(mcp, settings)
    return mcp


def create_app(settings: Settings) -> Starlette:
    mcp = create_mcp(settings)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Mount() does not run a sub-app's lifespan; without forwarding it the
    # session manager never starts and /mcp fails while /health still passes.
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=CredentialMiddleware(mcp_app))],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
