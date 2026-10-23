# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Companies (MSP clients), company notes, site configuration and configuration items."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, any_of, build, clean, op
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
    ToolInputError,
    belongs,
    create,
    require_any,
    search,
    title_from,
    tool,
    update,
    update_via_parent,
)

COMPANY_UPDATE_FIELDS = [
    "companyName", "phone", "address1", "address2", "city", "state", "postalCode", "countryID", "isActive",
    "webAddress", "billingAddress1", "billingAddress2", "billToAttention", "billToAddressToUse", "billToCity",
    "billToState", "billToZipCode", "billToCountryID", "billToCompanyLocationID", "taxRegionID",
    "invoiceTemplateID", "invoiceMethod", "invoiceEmailMessageID", "taxID", "isTaxExempt", "quoteEmailMessageID",
    "quoteTemplateID", "purchaseOrderTemplateID", "ownerResourceID", "classification", "companyType",
]  # fmt: skip

SITE_CONFIG_FIELDS = {"id", "companyID", "userDefinedFields"}


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_test_connection",
        "Check that the Autotask API is reachable with the supplied credentials. Returns the zone URL and the "
        "current API usage against the hourly threshold.",
        READ,
    )
    async def test_connection(c: AutotaskClient, a: Args) -> Any:
        info = await c.get("/ThresholdInformation") or {}
        return {
            "status": "ok",
            "message": "Autotask API is reachable and the credentials were accepted.",
            "zoneUrl": await c.base_url(),
            "threshold": clean(info),
        }

    @t(
        "autotask_search_companies",
        "Search companies (clients, prospects, vendors) by name or active status. Returns id, name and key fields; "
        "use the id with other tools.",
        READ,
        Opt("searchTerm", str, "Text contained in the company name."),
        Opt("isActive", bool, "Only active (true) or inactive (false) companies."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_companies(c: AutotaskClient, a: Args) -> Any:
        filters = build(("contains", "companyName", a.searchTerm), ("eq", "isActive", a.isActive))
        return await search(c, "Companies", filters, a)

    @t(
        "autotask_create_company",
        "Create a company. companyType is a picklist (see autotask_get_field_info, entityType Companies); "
        "ownerResourceID is the account manager and is usually required.",
        CREATE,
        Req("companyName", str, "Company name."),
        Req("companyType", int, "Company type picklist ID (e.g. Customer, Prospect, Vendor)."),
        Opt("phone", str, "Main phone number."),
        Opt("address1", str, "Street address."),
        Opt("city", str, "City."),
        Opt("state", str, "State or province."),
        Opt("postalCode", str, "Postal or ZIP code."),
        Opt("ownerResourceID", int, "Resource ID of the account owner."),
        Opt("isActive", bool, "Active flag (default true)."),
    )
    async def create_company(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            ["companyName", "companyType", "phone", "address1", "city", "state", "postalCode", "ownerResourceID"]
        )
        body["isActive"] = a.get("isActive", True)
        return await create(c, "Companies", body)

    @t(
        "autotask_update_company",
        "Update a company. Only the fields you pass are changed. invoiceTemplateID sets the invoice template "
        "(payment terms); billing address fields are separate from the main address.",
        UPDATE,
        Req("id", int, "Company ID."),
        Opt("companyName", str, "Company name."),
        Opt("phone", str, "Main phone number."),
        Opt("address1", str, "Street address line 1."),
        Opt("address2", str, "Street address line 2."),
        Opt("city", str, "City."),
        Opt("state", str, "State or province."),
        Opt("postalCode", str, "Postal or ZIP code."),
        Opt("countryID", int, "Country ID."),
        Opt("isActive", bool, "Active flag."),
        Opt("webAddress", str, "Website URL."),
        Opt("billingAddress1", str, "Billing address line 1."),
        Opt("billingAddress2", str, "Billing address line 2."),
        Opt("billToAttention", str, "Billing attention line."),
        Opt("billToAddressToUse", int, "Which address invoices use (picklist)."),
        Opt("billToCity", str, "Billing city."),
        Opt("billToState", str, "Billing state."),
        Opt("billToZipCode", str, "Billing postal code."),
        Opt("billToCountryID", int, "Billing country ID."),
        Opt("billToCompanyLocationID", int, "Billing company location ID."),
        Opt("taxRegionID", int, "Tax region ID."),
        Opt("invoiceTemplateID", int, "Invoice template ID."),
        Opt("invoiceMethod", int, "Invoice delivery method (picklist)."),
        Opt("invoiceEmailMessageID", int, "Invoice email message template ID."),
        Opt("taxID", str, "Tax ID."),
        Opt("isTaxExempt", bool, "Tax exempt flag."),
        Opt("quoteEmailMessageID", int, "Quote email message template ID."),
        Opt("quoteTemplateID", int, "Quote template ID."),
        Opt("purchaseOrderTemplateID", int, "Purchase order template ID."),
        Opt("ownerResourceID", int, "Account owner resource ID."),
        Opt("classification", int, "Classification picklist ID."),
        Opt("companyType", int, "Company type picklist ID."),
    )
    async def update_company(c: AutotaskClient, a: Args) -> Any:
        body = {"id": a.id, **a.fields(COMPANY_UPDATE_FIELDS)}
        require_any(body)
        return await update(c, "Companies", body)

    @t(
        "autotask_get_company_site_configuration",
        "Get the site configuration record(s) of a company. Their fields are tenant-defined custom fields; call this "
        "first to see the record ID and field names before updating.",
        READ,
        Req("companyId", int, "Company ID."),
    )
    async def get_site_configuration(c: AutotaskClient, a: Args) -> Any:
        rows = await c.query("CompanySiteConfigurations", build(("eq", "companyID", a.companyId)), 50)
        items = [clean(r) for r in rows]
        return {"items": items, "count": len(items)}

    @t(
        "autotask_update_company_site_configuration",
        "Update a company site configuration record. Pass the fields to change in updates: either "
        "{userDefinedFields: [{name, value}]} or plain {fieldName: value} pairs, which are sent as custom fields.",
        UPDATE,
        Req("id", int, "Site configuration record ID (from autotask_get_company_site_configuration)."),
        Req("updates", dict[str, Any], "Fields to change. Field names are tenant-specific."),
    )
    async def update_site_configuration(c: AutotaskClient, a: Args) -> Any:
        updates = dict(a.updates or {})
        if not updates:
            raise ToolInputError("updates is empty.")
        udfs = list(updates.pop("userDefinedFields", None) or [])
        body: dict[str, Any] = {"id": a.id}
        for key, value in updates.items():
            if key in SITE_CONFIG_FIELDS:
                if key != "id":
                    body[key] = value
            else:
                udfs.append({"name": key, "value": None if value is None else str(value)})
        if udfs:
            body["userDefinedFields"] = udfs

        async def parent() -> str:
            record = await c.get_item("CompanySiteConfigurations", a.id)
            return f"/Companies/{int(record['companyID'])}/SiteConfigurations"

        return await update_via_parent(c, "CompanySiteConfigurations", body, parent)

    @t(
        "autotask_get_company_note",
        "Get one company note by company ID and note ID.",
        READ,
        Req("companyId", int, "Company ID."),
        Req("noteId", int, "Company note ID."),
    )
    async def get_company_note(c: AutotaskClient, a: Args) -> Any:
        item = await c.get_item("CompanyNotes", a.noteId)
        return clean(belongs(item, "companyID", a.companyId, "Note"))

    @t(
        "autotask_search_company_notes",
        "List notes on one company. Scope the company first: looping over many companies uses up the API threshold.",
        READ,
        Req("companyId", int, "Company ID."),
        PAGE_SIZE,
    )
    async def search_company_notes(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "CompanyNotes", build(("eq", "companyID", a.companyId)), a)

    @t(
        "autotask_create_company_note",
        "Add a note to a company. actionType is a tenant picklist (autotask_get_field_info, entityType CompanyNotes).",
        CREATE,
        Req("companyId", int, "Company ID."),
        Opt("title", str, "Note title (defaults to the start of the description)."),
        Req("description", str, "Note text."),
        Opt("actionType", int, "Action type picklist ID."),
    )
    async def create_company_note(c: AutotaskClient, a: Args) -> Any:
        body = {
            "companyID": a.companyId,
            "title": a.title or title_from(a.description),
            "description": a.description,
            **a.fields(["actionType"]),
        }
        return await create(c, "CompanyNotes", body, f"/Companies/{a.companyId}/Notes")

    @t(
        "autotask_search_configuration_items",
        "Search configuration items (devices and assets) by name, serial number, company, product, type or category.",
        READ,
        Opt("searchTerm", str, "Text contained in the reference title, reference number or serial number."),
        Opt("companyID", int, "Company ID."),
        Opt("isActive", bool, "Only active (true) or inactive (false) items."),
        Opt("productID", int, "Product ID."),
        Opt("configurationItemType", int, "Configuration item type picklist ID."),
        Opt("configurationItemCategoryID", int, "Configuration item category ID."),
        PAGE_SIZE,
        PAGE,
    )
    async def search_configuration_items(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyID),
            ("eq", "isActive", a.isActive),
            ("eq", "productID", a.productID),
            ("eq", "configurationItemType", a.configurationItemType),
            ("eq", "configurationItemCategoryID", a.configurationItemCategoryID),
        )
        if a.searchTerm:
            filters.append(
                any_of(
                    op("contains", "referenceTitle", a.searchTerm),
                    op("contains", "referenceNumber", a.searchTerm),
                    op("contains", "serialNumber", a.searchTerm),
                )
            )
        return await search(c, "ConfigurationItems", filters, a)
