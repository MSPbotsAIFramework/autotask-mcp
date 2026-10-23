# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Finance: invoices, billing items, approval levels, billing codes and expense reports."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import ApiError, AutotaskClient, build, clean, op
from ..config import Settings
from ._common import CREATE, PAGE, PAGE_SIZE, READ, Args, Opt, Req, create, search, tool


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    # ---- invoices -------------------------------------------------------

    @t(
        "autotask_search_invoices",
        "Search invoices by company, invoice number or voided flag.",
        READ,
        Opt("companyID", int, "Company ID."),
        Opt("invoiceNumber", str, "Invoice number (exact)."),
        Opt("isVoided", bool, "Only voided (true) or not voided (false) invoices."),
        PAGE_SIZE,
    )
    async def search_invoices(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyID), ("eq", "invoiceNumber", a.invoiceNumber), ("eq", "isVoided", a.isVoided)
        )
        return await search(c, "Invoices", filters, a)

    @t(
        "autotask_get_invoice_details",
        "Get one invoice with its line items (the billing items posted to it).",
        READ,
        Req("invoiceId", int, "Invoice ID."),
    )
    async def get_invoice_details(c: AutotaskClient, a: Args) -> Any:
        invoice = clean(await c.get_item("Invoices", a.invoiceId))
        lines = await c.query("BillingItems", build(("eq", "invoiceID", a.invoiceId)), 500)
        lines.sort(key=lambda r: r.get("id") or 0)
        return {
            "invoice": invoice,
            "lineItems": [clean(r) for r in lines],
            "lineItemCount": len(lines),
            "lineItemsTruncated": len(lines) >= 500,
        }

    # ---- billing items --------------------------------------------------

    @t(
        "autotask_search_billing_items",
        "Search billing items: approved and posted billable work, charges and contract lines from Approve and Post. "
        "isInvoiced tells invoiced from not yet invoiced items.",
        READ,
        Opt("companyId", int, "Company ID."),
        Opt("ticketId", int, "Ticket ID."),
        Opt("projectId", int, "Project ID."),
        Opt("contractId", int, "Contract ID."),
        Opt("invoiceId", int, "Invoice ID."),
        Opt("isInvoiced", bool, "true = already on an invoice, false = not invoiced yet."),
        Opt("dateFrom", str, "itemDate on or after (ISO, e.g. 2026-01-01)."),
        Opt("dateTo", str, "itemDate on or before (ISO)."),
        Opt("postedAfter", str, "Posted on or after (ISO)."),
        Opt("postedBefore", str, "Posted on or before (ISO)."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_billing_items(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "companyID", a.companyId),
            ("eq", "ticketID", a.ticketId),
            ("eq", "projectID", a.projectId),
            ("eq", "contractID", a.contractId),
            ("eq", "invoiceID", a.invoiceId),
            ("gte", "itemDate", a.dateFrom),
            ("lte", "itemDate", a.dateTo),
            ("gte", "postedDate", a.postedAfter),
            ("lte", "postedDate", a.postedBefore),
        )
        if a.isInvoiced is not None:
            filters.append(op("exist" if a.isInvoiced else "notExist", "invoiceID"))
        return await search(c, "BillingItems", filters, a)

    @t(
        "autotask_get_billing_item",
        "Get one billing item by ID.",
        READ,
        Req("billingItemId", int, "Billing item ID."),
    )
    async def get_billing_item(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("BillingItems", a.billingItemId))

    @t(
        "autotask_search_billing_item_approval_levels",
        "Search multi-level approval records of time entries (who approved at which level and when).",
        READ,
        Opt("timeEntryId", int, "Time entry ID."),
        Opt("approvalResourceId", int, "Approving resource ID."),
        Opt("approvalLevel", int, "Approval level."),
        Opt("approvedAfter", str, "Approved on or after (ISO)."),
        Opt("approvedBefore", str, "Approved on or before (ISO)."),
        PAGE,
        PAGE_SIZE,
    )
    async def search_approval_levels(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("eq", "timeEntryID", a.timeEntryId),
            ("eq", "approvalResourceID", a.approvalResourceId),
            ("eq", "approvalLevel", a.approvalLevel),
            ("gte", "approvalDateTime", a.approvedAfter),
            ("lte", "approvalDateTime", a.approvedBefore),
        )
        return await search(c, "BillingItemApprovalLevels", filters, a)

    # ---- billing codes --------------------------------------------------

    @t(
        "autotask_search_billing_codes",
        "Search billing codes (allocation codes). A ticket's Work Type is a billing code: use useType 1 to list Work "
        "Types and pass the id as billingCodeID. useType 3 is internal time. Each result has useType and "
        "useTypeLabel. Active codes only unless includeInactive is true.",
        READ,
        Opt("name", str, "Text contained in the billing code name, e.g. Remote."),
        Opt(
            "useType",
            int,
            "Use type ID: 1 = Work Type (general), 3 = internal time. Full list: autotask_get_field_info "
            "(entityType BillingCodes, fieldName useType).",
        ),
        Opt("includeInactive", bool, "Include inactive billing codes (default false)."),
    )
    async def search_billing_codes(c: AutotaskClient, a: Args) -> Any:
        filters = build(("contains", "name", a.name), ("eq", "useType", a.useType))
        if not a.includeInactive:
            filters.append(op("eq", "isActive", True))
        rows = await c.query("BillingCodes", filters, 500)
        try:
            labels = {v["value"]: v["label"] for v in await c.picklist("BillingCodes", "useType", active_only=False)}
        except ApiError:
            labels = {}
        items = []
        for r in sorted(rows, key=lambda r: (r.get("useType") or 0, str(r.get("name") or ""))):
            row = clean(r)
            label = labels.get(r.get("useType"), labels.get(str(r.get("useType"))))
            if label:
                row["useTypeLabel"] = label
            items.append(row)
        return {"items": items, "count": len(items), "has_more": len(rows) >= 500}

    # ---- expense reports ------------------------------------------------

    @t(
        "autotask_get_expense_report",
        "Get one expense report by ID.",
        READ,
        Req("reportId", int, "Expense report ID."),
    )
    async def get_expense_report(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("ExpenseReports", a.reportId))

    @t(
        "autotask_search_expense_reports",
        "Search expense reports by submitter or status.",
        READ,
        Opt("submitterId", int, "Submitter resource ID."),
        Opt("status", int, "Status picklist ID."),
        PAGE_SIZE,
    )
    async def search_expense_reports(c: AutotaskClient, a: Args) -> Any:
        filters = build(("eq", "submitterID", a.submitterId), ("eq", "status", a.status))
        return await search(c, "ExpenseReports", filters, a)

    @t(
        "autotask_create_expense_report",
        "Create an expense report for a resource and week.",
        CREATE,
        Req("name", str, "Report name."),
        Opt("description", str, "Description."),
        Req("submitterId", int, "Submitter resource ID."),
        Req("weekEndingDate", str, "Week ending date (YYYY-MM-DD)."),
    )
    async def create_expense_report(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {"name": "name", "description": "description", "submitterId": "submitterID", "weekEndingDate": "weekEnding"}
        )
        return await create(c, "ExpenseReports", body)

    @t(
        "autotask_create_expense_item",
        "Add an expense line to an expense report. expenseCategory and paymentType are picklists "
        "(autotask_get_field_info, entityType ExpenseItems).",
        CREATE,
        Req("expenseReportId", int, "Expense report ID."),
        Req("description", str, "Line description."),
        Req("expenseDate", str, "Expense date (YYYY-MM-DD)."),
        Req("expenseCategory", int, "Expense category picklist ID."),
        Req("amount", float, "Amount in the expense currency."),
        Opt("companyId", int, "Company ID (0 for internal)."),
        Opt("haveReceipt", bool, "A receipt is available."),
        Opt("isBillableToCompany", bool, "Billable to the company."),
        Opt("isReimbursable", bool, "Reimbursable to the submitter."),
        Opt("paymentType", int, "Payment type picklist ID."),
    )
    async def create_expense_item(c: AutotaskClient, a: Args) -> Any:
        body = a.fields(
            {
                "expenseReportId": "expenseReportID",
                "description": "description",
                "expenseDate": "expenseDate",
                "expenseCategory": "expenseCategory",
                "amount": "expenseCurrencyExpenseAmount",
                "companyId": "companyID",
                "haveReceipt": "haveReceipt",
                "isBillableToCompany": "isBillableToCompany",
                "isReimbursable": "isReimbursable",
                "paymentType": "paymentType",
            }
        )
        return await create(c, "ExpenseItems", body, f"/Expenses/{a.expenseReportId}/Items")
