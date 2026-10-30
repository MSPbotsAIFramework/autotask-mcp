# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Contacts (people at client companies).

Some zones do not register the collection-level ``/Contacts`` route for writes and answer
``POST``/``PATCH /Contacts`` with an HTML 404. Writes therefore fall back to the parent-scoped
``/Companies/{companyID}/Contacts`` URL on 404/405.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, any_of, build, op
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
    create,
    require_any,
    search,
    tool,
    update_via_parent,
)

UPDATE_FIELDS = [
    "firstName", "lastName", "emailAddress", "phone", "title", "mobilePhone", "addressLine", "addressLine1",
    "city", "state", "zipCode", "countryID", "userDefinedFields",
]  # fmt: skip


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_search_contacts",
        "Search contacts by name or email, optionally within one company. Custom fields are left out unless "
        "includeUserDefinedFields is true.",
        READ,
        Opt("searchTerm", str, "Text contained in the first name, last name or email address."),
        Opt("email", str, "Exact match against emailAddress, emailAddress2, or emailAddress3."),
        Opt("companyID", int, "Company ID."),
        Opt("isActive", int, "1 = active only, 0 = inactive only."),
        PAGE,
        PAGE_SIZE,
        Opt(
            "includeUserDefinedFields",
            bool,
            "Include each contact's custom fields (userDefinedFields, a list of {name, value}). Default false.",
        ),
    )
    async def search_contacts(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "companyID", a.companyID), ("eq", "isActive", a.isActive))
        if a.searchTerm:
            term = a.searchTerm.strip()
            options = [
                op("contains", "firstName", term),
                op("contains", "lastName", term),
                op("contains", "emailAddress", term),
            ]
            parts = term.split()
            if len(parts) >= 2:  # "Jane Doe" -> first name AND last name
                options.append(
                    {
                        "op": "and",
                        "items": [
                            op("beginsWith", "firstName", parts[0]),
                            op("beginsWith", "lastName", " ".join(parts[1:])),
                        ],
                    }
                )
            filters.append(any_of(*options))
        if a.email:
            filters.append(
                any_of(
                    op("eq", "emailAddress", a.email),
                    op("eq", "emailAddress2", a.email),
                    op("eq", "emailAddress3", a.email),
                )
            )
        drop = None if a.includeUserDefinedFields else {"userDefinedFields"}
        return await search(c, "Contacts", filters, a, drop=drop)

    @t(
        "autotask_create_contact",
        "Create a contact in a company. isActive defaults to 1 (active).",
        CREATE,
        Req("companyID", int, "Company ID the contact belongs to."),
        Req("firstName", str, "First name."),
        Req("lastName", str, "Last name."),
        Opt("emailAddress", str, "Primary email address."),
        Opt("phone", str, "Primary phone number."),
        Opt("title", str, "Job title."),
        Opt("isActive", int, "1 = active (default), 0 = inactive."),
    )
    async def create_contact(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(["companyID", "firstName", "lastName", "emailAddress", "phone", "title"])
        body["isActive"] = a.get("isActive", 1)
        return await create(c, "Contacts", body, f"/Companies/{a.companyID}/Contacts")

    @t(
        "autotask_update_contact",
        "Update a contact. Only the fields you pass are changed. userDefinedFields is a list of {name, value}.",
        UPDATE,
        Req("id", int, "Contact ID."),
        Opt("firstName", str, "First name."),
        Opt("lastName", str, "Last name."),
        Opt("emailAddress", str, "Primary email address."),
        Opt("phone", str, "Primary phone number."),
        Opt("title", str, "Job title."),
        Opt("isActive", bool, "Whether the contact is active."),
        Opt("mobilePhone", str, "Mobile phone number."),
        Opt("addressLine", str, "Address line (primary)."),
        Opt("addressLine1", str, "Address line 1 (secondary)."),
        Opt("city", str, "City."),
        Opt("state", str, "State or province."),
        Opt("zipCode", str, "Postal or ZIP code."),
        Opt("countryID", int, "Country ID."),
        Opt("primaryContact", bool, "Whether this is the company's primary contact."),
        Opt("userDefinedFields", list[dict[str, Any]], "Custom fields as a list of {name, value}."),
    )
    async def update_contact(c: AutotaskClient, a: Args) -> Any:
        body: dict[str, Any] = {"id": a.id, **a.fields(UPDATE_FIELDS)}
        if a.isActive is not None:
            body["isActive"] = 1 if a.isActive else 0
        if a.primaryContact is not None:
            body["primaryContact"] = a.primaryContact
        require_any(body)

        async def parent() -> str:
            contact = await c.get_item("Contacts", a.id)
            return f"/Companies/{int(contact['companyID'])}/Contacts"

        return await update_via_parent(c, "Contacts", body, parent)
