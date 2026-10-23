# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Contracts, their service and bundle lines, billed units and recurring-revenue roll-up."""

import datetime as dt
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import ApiError, AutotaskClient, build, clean, op
from ..config import Settings
from ._common import (
    CREATE,
    MAX_PAGE_SIZE,
    PAGE_SIZE,
    READ,
    UPDATE,
    Args,
    Opt,
    Param,
    Req,
    ToolInputError,
    create,
    require_any,
    search,
    tool,
    update,
)

CONTRACT_FIELDS = [
    "companyID", "contractName", "contractType", "contractCategory", "startDate", "endDate", "contactID",
    "contractNumber", "contractPeriodType", "description", "estimatedCost", "estimatedHours", "estimatedRevenue",
    "setupFee", "overageBillingRate", "serviceLevelAgreementID", "purchaseOrderNumber", "opportunityID",
    "billingPreference", "billToCompanyID", "billToCompanyContactID", "exclusionContractID", "isDefaultContract",
    "internalCurrencySetupFee", "internalCurrencyOverageBillingRate", "organizationalLevelAssociationID",
    "contractExclusionSetID", "renewedContractID", "setupFeeBillingCodeID", "status",
    "timeReportingRequiresStartAndStopTimes",
]  # fmt: skip
CONTRACT_REQUIRED = ["companyID", "contractName", "contractType", "contractCategory", "startDate", "endDate"]
SERVICE_FIELDS = [
    "contractID", "serviceID", "unitPrice", "unitCost", "quoteItemID", "internalCurrencyUnitPrice", "adjustedPrice",
    "invoiceDescription",
]  # fmt: skip

# Monthly factor by words found in a period type label (Services / ServiceBundles periodType picklist).
PERIOD_FACTORS = [
    ("semi", 1 / 6),
    ("quarter", 1 / 3),
    ("year", 1 / 12),
    ("annual", 1 / 12),
    ("month", 1.0),
    ("week", 52 / 12),
]


def _contract_params(required: bool) -> list[Param]:
    types: dict[str, Any] = {
        "contractName": str, "startDate": str, "endDate": str, "contractNumber": str, "description": str,
        "purchaseOrderNumber": str, "estimatedCost": float, "estimatedHours": float, "estimatedRevenue": float,
        "setupFee": float, "overageBillingRate": float, "internalCurrencySetupFee": float,
        "internalCurrencyOverageBillingRate": float, "isDefaultContract": bool,
    }  # fmt: skip
    notes = {
        "status": "1 = In Effect, 0 = Inactive.",
        "startDate": "Start date (YYYY-MM-DD).",
        "endDate": "End date (YYYY-MM-DD).",
        "contractType": "Contract type picklist ID.",
        "contractCategory": "Contract category picklist ID.",
        "timeReportingRequiresStartAndStopTimes": "1 = time entries need start and stop times.",
    }
    out = []
    for name in CONTRACT_FIELDS:
        description = notes.get(name, f"Contract field {name}.")
        is_required = required and name in CONTRACT_REQUIRED
        out.append(Param(name, types.get(name, int), description, is_required))
    return out


def _today() -> str:
    return dt.date.today().isoformat()


def _active_on(a: Args) -> str:
    value = (a.activeOn or _today()).strip()
    try:
        dt.date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ToolInputError("activeOn must be a date like 2026-01-31.") from exc
    return value[:10]


def _unit_filters(contract_id: int, day: str) -> list[dict[str, Any]]:
    return [op("eq", "contractID", contract_id), op("lte", "startDate", day), op("gte", "endDate", day)]


def _factor(label: str | None) -> float | None:
    text = (label or "").lower()
    for word, factor in PERIOD_FACTORS:
        if word in text:
            return factor
    return None


def register(mcp: FastMCP, settings: Settings) -> None:
    def t(*a, **k):
        return tool(mcp, settings, *a, **k)

    @t(
        "autotask_search_contracts",
        "Search contracts by name, company, status, type or end date range.",
        READ,
        Opt("searchTerm", str, "Text contained in the contract name."),
        Opt("companyID", int, "Company ID."),
        Opt("status", int, "1 = In Effect, 0 = Inactive."),
        Opt("contractType", int, "Contract type picklist ID."),
        Opt("endDateFrom", str, "End date on or after (YYYY-MM-DD)."),
        Opt("endDateTo", str, "End date on or before (YYYY-MM-DD)."),
        PAGE_SIZE,
    )
    async def search_contracts(c: AutotaskClient, a: Args) -> Any:
        filters = build(
            ("contains", "contractName", a.searchTerm),
            ("eq", "companyID", a.companyID),
            ("eq", "status", a.status),
            ("eq", "contractType", a.contractType),
            ("gte", "endDate", a.endDateFrom),
            ("lte", "endDate", a.endDateTo),
        )
        return await search(c, "Contracts", filters, a)

    @t(
        "autotask_get_contract",
        "Get one contract by ID (header fields only; use the contract service tools for lines).",
        READ,
        Req("id", int, "Contract ID."),
    )
    async def get_contract(c: AutotaskClient, a: Args) -> Any:
        return clean(await c.get_item("Contracts", a.id))

    @t(
        "autotask_list_expiring_contracts",
        "List contracts whose end date falls within the next daysAhead days (default 60), soonest first. Optionally "
        "include already expired contracts and limit to one company.",
        READ,
        Opt("daysAhead", int, "Look-ahead window in days (default 60)."),
        Opt("companyID", int, "Company ID (omit for all companies)."),
        Opt("includeExpired", bool, "Also include contracts that already ended (default false)."),
        Opt("status", int, "Contract status (1 = In Effect)."),
        Opt("pageSize", int, f"Maximum results (default 100, max {MAX_PAGE_SIZE})."),
    )
    async def list_expiring(c: AutotaskClient, a: Args) -> Any:
        days = max(int(a.get("daysAhead", 60)), 0)
        today = dt.date.today()
        horizon = (today + dt.timedelta(days=days)).isoformat()
        filters = build(
            ("lte", "endDate", horizon),
            ("gte", "endDate", None if a.includeExpired else today.isoformat()),
            ("eq", "companyID", a.companyID),
            ("eq", "status", a.status),
        )
        size = min(max(int(a.get("pageSize", 100)), 1), MAX_PAGE_SIZE)
        rows = await c.query("Contracts", filters, size + 1)
        rows.sort(key=lambda r: str(r.get("endDate") or ""))
        items = []
        for r in rows[:size]:
            row = clean(r)
            try:
                row["daysUntilEnd"] = (dt.date.fromisoformat(str(r.get("endDate"))[:10]) - today).days
            except ValueError:
                pass
            items.append(row)
        return {"items": items, "count": len(items), "has_more": len(rows) > size, "endDateTo": horizon}

    # ---- lines ----------------------------------------------------------

    @t(
        "autotask_search_contract_services",
        "List the service lines on a contract (ContractServices): which catalog services and at what contract unit "
        "price. Pair with autotask_search_contract_service_units for billed quantities, or use "
        "autotask_get_contract_recurring_lines for both.",
        READ,
        Req("contractID", int, "Contract ID."),
        PAGE_SIZE,
    )
    async def search_contract_services(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "ContractServices", build(("eq", "contractID", a.contractID)), a)

    @t(
        "autotask_search_contract_service_units",
        "Billed unit rows of a contract's service lines (ContractServiceUnits) active on a day (default today): "
        "what is currently being invoiced.",
        READ,
        Req("contractID", int, "Contract ID."),
        Opt("activeOn", str, "Date (YYYY-MM-DD) the rows must cover. Default today."),
        Opt("pageSize", int, f"Maximum rows (default {MAX_PAGE_SIZE}, max {MAX_PAGE_SIZE})."),
    )
    async def search_service_units(c: AutotaskClient, a: Args) -> Any:
        return await _units(c, "ContractServiceUnits", a)

    @t(
        "autotask_search_contract_service_bundles",
        "List the service bundle lines on a contract (ContractServiceBundles).",
        READ,
        Req("contractID", int, "Contract ID."),
        PAGE_SIZE,
    )
    async def search_contract_bundles(c: AutotaskClient, a: Args) -> Any:
        return await search(c, "ContractServiceBundles", build(("eq", "contractID", a.contractID)), a)

    @t(
        "autotask_search_contract_service_bundle_units",
        "Billed unit rows of a contract's bundle lines (ContractServiceBundleUnits) active on a day (default today).",
        READ,
        Req("contractID", int, "Contract ID."),
        Opt("activeOn", str, "Date (YYYY-MM-DD) the rows must cover. Default today."),
        Opt("pageSize", int, f"Maximum rows (default {MAX_PAGE_SIZE}, max {MAX_PAGE_SIZE})."),
    )
    async def search_bundle_units(c: AutotaskClient, a: Args) -> Any:
        return await _units(c, "ContractServiceBundleUnits", a)

    @t(
        "autotask_get_contract_recurring_lines",
        "Recurring revenue of one contract: every service and bundle line with units active on a day, with catalog "
        "name and billing period, normalized to monthly amounts. Returns lines, monthlyTotal, monthlyCost and "
        "unresolvedPeriodTypes. Use it for MRR and 'what does this client pay for' questions.",
        READ,
        Req("contractID", int, "Contract ID."),
        Opt("activeOn", str, "Date (YYYY-MM-DD) the lines must be active on. Default today."),
    )
    async def recurring_lines(c: AutotaskClient, a: Args) -> Any:
        day = _active_on(a)
        contract = await c.get_item("Contracts", a.contractID)
        company_name = None
        if contract.get("companyID") is not None:
            try:
                company_name = (await c.get_item("Companies", int(contract["companyID"]))).get("companyName")
            except ApiError:
                company_name = None

        lines: list[dict[str, Any]] = []
        unresolved: set[str] = set()
        total = cost_total = 0.0
        for unit_entity, catalog, ref in (
            ("ContractServiceUnits", "Services", "serviceID"),
            ("ContractServiceBundleUnits", "ServiceBundles", "serviceBundleID"),
        ):
            units = await c.query(unit_entity, _unit_filters(a.contractID, day), 500)
            if not units:
                continue
            ids = sorted({int(u[ref]) for u in units if u.get(ref) is not None})
            items = {int(s["id"]): s for s in await c.query(catalog, [op("in", "id", ids)], 500)} if ids else {}
            try:
                periods = {v["value"]: v["label"] for v in await c.picklist(catalog, "periodType", active_only=False)}
            except ApiError:
                periods = {}
            for u in units:
                entry = items.get(int(u[ref])) if u.get(ref) is not None else None
                period_value = (entry or {}).get("periodType")
                label = periods.get(period_value, periods.get(str(period_value)))
                factor = _factor(label)
                qty = float(u.get("units") or 0)
                price = float(u.get("price") or 0)
                cost = float(u.get("cost") or 0)
                line = {
                    "type": "bundle" if ref == "serviceBundleID" else "service",
                    ref: u.get(ref),
                    "name": (entry or {}).get("name"),
                    "vendorCompanyID": (entry or {}).get("vendorCompanyID"),
                    "periodType": label or period_value,
                    "units": qty,
                    "unitPrice": price,
                    "unitCost": cost,
                    "startDate": u.get("startDate"),
                    "endDate": u.get("endDate"),
                }
                if factor is None:
                    unresolved.add(str(label or period_value))
                else:
                    line["monthlyAmount"] = round(qty * price * factor, 2)
                    line["monthlyCost"] = round(qty * cost * factor, 2)
                    total += line["monthlyAmount"]
                    cost_total += line["monthlyCost"]
                lines.append(clean(line))
        return {
            "contractID": a.contractID,
            "contractName": contract.get("contractName"),
            "companyID": contract.get("companyID"),
            "companyName": company_name,
            "activeOn": day,
            "lines": lines,
            "monthlyTotal": round(total, 2),
            "monthlyCost": round(cost_total, 2),
            "unresolvedPeriodTypes": sorted(unresolved),
        }

    # ---- writes ---------------------------------------------------------

    @t(
        "autotask_create_contract",
        "Create a contract (header only). Field names match the Autotask API. status: 1 = In Effect, 0 = Inactive. "
        "Dates are YYYY-MM-DD.",
        CREATE,
        *_contract_params(required=True),
    )
    async def create_contract(c: AutotaskClient, a: Args) -> Any:
        return await create(c, "Contracts", a.fields(CONTRACT_FIELDS))

    @t(
        "autotask_create_contracts_bulk",
        "Create up to 50 contract headers in one call (e.g. one per location). They are created one at a time; a "
        "failure does not stop the rest and each item reports its own result.",
        CREATE,
        Req(
            "contracts",
            list[dict[str, Any]],
            "Contracts to create, in order, with the autotask_create_contract fields.",
        ),
    )
    async def create_contracts_bulk(c: AutotaskClient, a: Args) -> Any:
        contracts = a.contracts or []
        if not contracts or len(contracts) > 50:
            raise ToolInputError("contracts must hold between 1 and 50 entries.")
        results = []
        for index, raw in enumerate(contracts):
            if not isinstance(raw, dict):
                results.append({"index": index, "success": False, "error": "Entry is not an object."})
                continue
            missing = [k for k in CONTRACT_REQUIRED if raw.get(k) in (None, "")]
            if missing:
                results.append({"index": index, "success": False, "error": f"Missing: {', '.join(missing)}."})
                continue
            body = {k: raw[k] for k in CONTRACT_FIELDS if raw.get(k) is not None}
            try:
                created = await create(c, "Contracts", body)
                results.append({"index": index, "success": True, "id": created["id"]})
            except ApiError as exc:
                results.append({"index": index, "success": False, "error": exc.message, "code": exc.code})
        ok = sum(1 for r in results if r["success"])
        return {"created": ok, "failed": len(results) - ok, "results": results}

    @t(
        "autotask_update_contract",
        "Update a contract (PATCH). Pass only the fields to change. status: 1 = In Effect, 0 = Inactive.",
        UPDATE,
        Req("id", int, "Contract ID."),
        *_contract_params(required=False),
    )
    async def update_contract(c: AutotaskClient, a: Args) -> Any:
        body = {"id": a.id, **a.fields(CONTRACT_FIELDS)}
        require_any(body)
        return await update(c, "Contracts", body)

    @t(
        "autotask_create_contract_service",
        "Add a service line (ContractService) to a contract.",
        CREATE,
        Req("contractID", int, "Contract ID."),
        Req("serviceID", int, "Service ID from the catalog."),
        Req("unitPrice", float, "Contract unit price."),
        Opt("unitCost", float, "Unit cost."),
        Opt("quoteItemID", int, "Quote item ID the line comes from."),
        Opt("internalCurrencyUnitPrice", float, "Unit price in internal currency."),
        Opt("adjustedPrice", float, "Adjusted price."),
        Opt("invoiceDescription", str, "Text printed on invoices."),
    )
    async def create_contract_service(c: AutotaskClient, a: Args) -> Any:
        return await create(c, "ContractServices", a.fields(SERVICE_FIELDS), f"/Contracts/{a.contractID}/Services")

    @t(
        "autotask_update_contract_service",
        "Update a service line (ContractService) on a contract. Pass only the fields to change.",
        UPDATE,
        Req("id", int, "Contract service ID."),
        Req("contractID", int, "Contract ID."),
        Opt("serviceID", int, "Service ID."),
        Opt("unitPrice", float, "Contract unit price."),
        Opt("unitCost", float, "Unit cost."),
        Opt("quoteItemID", int, "Quote item ID."),
        Opt("internalCurrencyUnitPrice", float, "Unit price in internal currency."),
        Opt("adjustedPrice", float, "Adjusted price."),
        Opt("invoiceDescription", str, "Text printed on invoices."),
    )
    async def update_contract_service(c: AutotaskClient, a: Args) -> Any:
        body = {"id": a.id, **a.fields(SERVICE_FIELDS)}
        require_any({k: v for k, v in body.items() if k != "contractID"})
        return await update(c, "ContractServices", body, f"/Contracts/{a.contractID}/Services")


async def _units(c: AutotaskClient, entity: str, a: Args) -> dict[str, Any]:
    day = _active_on(a)
    size = min(max(int(a.get("pageSize", MAX_PAGE_SIZE)), 1), MAX_PAGE_SIZE)
    rows = await c.query(entity, _unit_filters(a.contractID, day), size + 1)
    rows.sort(key=lambda r: r.get("id") or 0)
    items = [clean(r) for r in rows[:size]]
    return {"items": items, "count": len(items), "has_more": len(rows) > size, "activeOn": day}
