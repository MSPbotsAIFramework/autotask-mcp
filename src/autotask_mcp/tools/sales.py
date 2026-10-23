# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Sales: opportunities, quotes and quote items, and the product / service catalog."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import AutotaskClient, build, clean
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
    ToolInputError,
    create,
    remove,
    require_any,
    search,
    tool,
    update_via_parent,
)

ITEM_TYPE_BY_REFERENCE = {"productID": 1, "serviceID": 11, "serviceBundleID": 12}


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    def getter(name: str, entity: str, label: str, param: str) -> None:
        @t(name, f"Get one {label} by ID.", READ, Req(param, int, f"{label[0].upper()}{label[1:]} ID."))
        async def handler(c: AutotaskClient, a: Args) -> Any:
            return clean(await c.get_item(entity, getattr(a, param)))

    def catalog_search(name: str, entity: str, label: str) -> None:
        @t(
            name,
            f"Search {label} by name and active status.",
            READ,
            Opt("searchTerm", str, "Text contained in the name."),
            Opt("isActive", bool, "Only active (true) or inactive (false) records."),
            PAGE_SIZE,
        )
        async def handler(c: AutotaskClient, a: Args) -> Any:
            filters = build(("contains", "name", a.searchTerm), ("eq", "isActive", a.isActive))
            return await search(c, entity, filters, a)

    # ---- catalog --------------------------------------------------------

    getter("autotask_get_product", "Products", "product", "productId")
    catalog_search("autotask_search_products", "Products", "products")
    getter("autotask_get_service", "Services", "service", "serviceId")
    catalog_search("autotask_search_services", "Services", "services (recurring catalog items)")
    getter("autotask_get_service_bundle", "ServiceBundles", "service bundle", "serviceBundleId")
    catalog_search("autotask_search_service_bundles", "ServiceBundles", "service bundles")

    # ---- opportunities --------------------------------------------------

    getter("autotask_get_opportunity", "Opportunities", "opportunity", "opportunityId")

    @t(
        "autotask_search_opportunities",
        "Search sales opportunities by company, title or status.",
        READ,
        Opt("companyId", int, "Company ID."),
        Opt("searchTerm", str, "Text contained in the opportunity title."),
        Opt("status", int, "Opportunity status picklist ID."),
        PAGE_SIZE,
    )
    async def search_opportunities(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyId), ("contains", "title", a.searchTerm), ("eq", "status", a.status)
        )
        return await search(c, "Opportunities", filters, a)

    @t(
        "autotask_create_opportunity",
        "Create a sales opportunity. status and stage are picklists (autotask_get_field_info, entityType "
        "Opportunities).",
        CREATE,
        Req("title", str, "Opportunity title."),
        Req("companyId", int, "Company ID."),
        Req("ownerResourceId", int, "Owner (sales rep) resource ID."),
        Req("status", int, "Status picklist ID."),
        Req("stage", int, "Stage picklist ID."),
        Req("projectedCloseDate", str, "Projected close date (YYYY-MM-DD)."),
        Req("startDate", str, "Start date (YYYY-MM-DD)."),
        Opt("probability", int, "Win probability in percent."),
        Opt("amount", float, "Total revenue amount."),
        Opt("cost", float, "Total cost."),
        Opt("useQuoteTotals", bool, "Take amounts from the primary quote."),
        Opt("totalAmountMonths", int, "Number of months the amount covers."),
        Opt("contactId", int, "Contact ID."),
        Opt("description", str, "Description."),
        Opt("opportunityCategoryID", int, "Opportunity category ID."),
    )
    async def create_opportunity(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {
                "title": "title",
                "companyId": "companyID",
                "ownerResourceId": "ownerResourceID",
                "status": "status",
                "stage": "stage",
                "projectedCloseDate": "projectedCloseDate",
                "startDate": "startDate",
                "probability": "probability",
                "amount": "amount",
                "cost": "cost",
                "useQuoteTotals": "useQuoteTotals",
                "totalAmountMonths": "totalAmountMonths",
                "contactId": "contactID",
                "description": "description",
                "opportunityCategoryID": "opportunityCategoryID",
            }
        )
        return await create(c, "Opportunities", body)

    # ---- quotes ---------------------------------------------------------

    getter("autotask_get_quote", "Quotes", "quote", "quoteId")

    @t(
        "autotask_search_quotes",
        "Search quotes by company, contact, opportunity or name.",
        READ,
        Opt("companyId", int, "Company ID."),
        Opt("contactId", int, "Contact ID."),
        Opt("opportunityId", int, "Opportunity ID."),
        Opt("searchTerm", str, "Text contained in the quote name."),
        PAGE_SIZE,
    )
    async def search_quotes(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyId),
            ("eq", "contactID", a.contactId),
            ("eq", "opportunityID", a.opportunityId),
            ("contains", "name", a.searchTerm),
        )
        return await search(c, "Quotes", filters, a)

    @t(
        "autotask_create_quote",
        "Create a quote for a company. Autotask usually also needs effectiveDate and expirationDate.",
        CREATE,
        Opt("name", str, "Quote name."),
        Opt("description", str, "Description."),
        Req("companyId", int, "Company ID."),
        Opt("contactId", int, "Contact ID."),
        Opt("opportunityId", int, "Opportunity ID."),
        Opt("effectiveDate", str, "Effective date (YYYY-MM-DD)."),
        Opt("expirationDate", str, "Expiration date (YYYY-MM-DD)."),
    )
    async def create_quote(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {
                "name": "name",
                "description": "description",
                "companyId": "companyID",
                "contactId": "contactID",
                "opportunityId": "opportunityID",
                "effectiveDate": "effectiveDate",
                "expirationDate": "expirationDate",
            }
        )
        return await create(c, "Quotes", body)

    # ---- quote items ----------------------------------------------------

    getter("autotask_get_quote_item", "QuoteItems", "quote item", "quoteItemId")

    @t(
        "autotask_search_quote_items",
        "Search quote line items, usually by quote ID.",
        READ,
        Opt("quoteId", int, "Quote ID."),
        Opt("searchTerm", str, "Text contained in the item name."),
        PAGE_SIZE,
    )
    async def search_quote_items(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "quoteID", a.quoteId), ("contains", "name", a.searchTerm))
        return await search(c, "QuoteItems", filters, a)

    @t(
        "autotask_create_quote_item",
        "Add a line item to a quote. Set at most one of serviceID, productID or serviceBundleID; quoteItemType is "
        "derived from it when omitted. Discounts default to 0 and isOptional to false.",
        CREATE,
        Req("quoteId", int, "Quote ID."),
        Opt("name", str, "Item name (filled in by Autotask for product and service items)."),
        Opt("description", str, "Description."),
        Req("quantity", float, "Quantity."),
        Opt("unitPrice", float, "Unit price."),
        Opt("unitCost", float, "Unit cost."),
        Opt("unitDiscount", float, "Per-unit discount amount (default 0)."),
        Opt("lineDiscount", float, "Line discount amount (default 0)."),
        Opt("percentageDiscount", float, "Percentage discount (default 0)."),
        Opt("isOptional", bool, "Optional line item (default false)."),
        Opt("serviceID", int, "Service ID."),
        Opt("productID", int, "Product ID."),
        Opt("serviceBundleID", int, "Service bundle ID."),
        Opt("sortOrderID", int, "Display order."),
        Opt("quoteItemType", int, "1 Product, 2 Cost, 3 Labor, 4 Expense, 6 Shipping, 11 Service, 12 Service bundle."),
    )
    async def create_quote_item(c: AutotaskClient, a: Args) -> Any:
        refs = [k for k in ITEM_TYPE_BY_REFERENCE if getattr(a, k) is not None]
        if len(refs) > 1:
            raise ToolInputError("Set at most one of serviceID, productID or serviceBundleID.")
        body = {
            "quoteID": a.quoteId,
            "quantity": a.quantity,
            "unitDiscount": a.get("unitDiscount", 0),
            "lineDiscount": a.get("lineDiscount", 0),
            "percentageDiscount": a.get("percentageDiscount", 0),
            "isOptional": a.get("isOptional", False),
            **a.fields(
                [
                    "name",
                    "description",
                    "unitPrice",
                    "unitCost",
                    "serviceID",
                    "productID",
                    "serviceBundleID",
                    "sortOrderID",
                    "quoteItemType",
                ]
            ),  # fmt: skip
        }
        if "quoteItemType" not in body and refs:
            body["quoteItemType"] = ITEM_TYPE_BY_REFERENCE[refs[0]]
        return await create(c, "QuoteItems", body, f"/Quotes/{a.quoteId}/Items")

    @t(
        "autotask_update_quote_item",
        "Update a quote item (quantity, price, discounts, optional flag, order). Only passed fields change.",
        UPDATE,
        Req("quoteItemId", int, "Quote item ID."),
        Opt("quantity", float, "Quantity."),
        Opt("unitPrice", float, "Unit price."),
        Opt("unitDiscount", float, "Per-unit discount amount."),
        Opt("lineDiscount", float, "Line discount amount."),
        Opt("percentageDiscount", float, "Percentage discount."),
        Opt("isOptional", bool, "Optional line item."),
        Opt("sortOrderID", int, "Display order."),
    )
    async def update_quote_item(c: AutotaskClient, a: Args) -> Any:
        fields = ["quantity", "unitPrice", "unitDiscount", "lineDiscount", "percentageDiscount", "isOptional"]
        body = {"id": a.quoteItemId, **a.fields([*fields, "sortOrderID"])}
        require_any(body)

        async def parent() -> str:
            item = await c.get_item("QuoteItems", a.quoteItemId)
            return f"/Quotes/{int(item['quoteID'])}/Items"

        return await update_via_parent(c, "QuoteItems", body, parent)

    @t(
        "autotask_delete_quote_item",
        f"Delete a line item from a quote. {DELETE_WARNING}",
        DESTRUCTIVE,
        Req("quoteId", int, "Quote ID."),
        Req("quoteItemId", int, "Quote item ID."),
        title="Delete quote item (irreversible)",
    )
    async def delete_quote_item(c: AutotaskClient, a: Args) -> Any:
        paths = [f"/Quotes/{a.quoteId}/Items/{a.quoteItemId}", f"/QuoteItems/{a.quoteItemId}"]
        return await remove(c, paths, a.quoteItemId, "QuoteItems")
