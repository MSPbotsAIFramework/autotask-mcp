# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tool behaviour against a mocked Autotask API."""

import base64
import json

import httpx
import pytest
import respx
from conftest import ZONE, make_creds

from autotask_mcp import credentials
from autotask_mcp.config import ZONE_LOOKUP_URL

pytestmark = pytest.mark.usefixtures("creds")


def body_of(route):
    return json.loads(route.calls.last.request.content)


def with_creds(**overrides):
    return credentials._current.set(make_creds(**overrides))


@respx.mock
async def test_auth_headers_and_zone_from_header(call):
    route = respx.get(f"{ZONE}/ThresholdInformation").mock(
        return_value=httpx.Response(200, json={"externalRequestThreshold": 10000, "currentTimeframeRequestCount": 5})
    )
    out = await call("autotask_test_connection")
    req = route.calls.last.request
    assert req.headers["UserName"] == "api-user@example.com"
    assert req.headers["Secret"] == "YOUR_API_SECRET"
    assert req.headers["ApiIntegrationCode"] == "YOUR_INTEGRATION_CODE"
    assert out["status"] == "ok" and out["zoneUrl"] == ZONE


@respx.mock
async def test_zone_lookup_when_no_url_header(call):
    lookup = respx.get(ZONE_LOOKUP_URL).mock(
        return_value=httpx.Response(200, json={"url": "https://webservices7.autotask.net/ATServicesRest/"})
    )
    api = respx.get("https://webservices7.autotask.net/ATServicesRest/v1.0/ThresholdInformation").mock(
        return_value=httpx.Response(200, json={})
    )
    token = with_creds(api_url=None)
    try:
        out = await call("autotask_test_connection")
        await call("autotask_test_connection")
    finally:
        credentials._current.reset(token)
    assert out["status"] == "ok"
    assert lookup.calls.last.request.url.params["user"] == "api-user@example.com"
    assert "Secret" not in lookup.calls.last.request.headers
    assert lookup.call_count == 2  # once per tool call, never cached across requests
    assert api.call_count == 2


@respx.mock
async def test_zone_lookup_rejects_foreign_host(call):
    respx.get(ZONE_LOOKUP_URL).mock(return_value=httpx.Response(200, json={"url": "https://evil.example.com/"}))
    token = with_creds(api_url=None)
    try:
        out = await call("autotask_test_connection")
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"


@pytest.mark.parametrize("url", ["probe-placeholder", "http://webservices5.autotask.net", "https://example.com"])
async def test_bad_api_url_is_reported_by_tool(call, url):
    token = with_creds(api_url=url)
    try:
        out = await call("autotask_test_connection")
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"


async def test_missing_integration_code(call):
    token = with_creds(integration_code=None)
    try:
        out = await call("autotask_search_companies")
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"
    assert "X-Integration-Code" in out["error"]["message"]


async def test_missing_credentials_envelope(call):
    token = credentials._current.set(None)
    try:
        out = await call("autotask_search_companies")
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"


@respx.mock
async def test_search_companies_filters_and_has_more(call):
    rows = [{"id": i, "companyName": f"Acme {i}", "phone": None} for i in range(1, 4)]
    route = respx.post(f"{ZONE}/Companies/query").mock(return_value=httpx.Response(200, json={"items": rows}))
    out = await call("autotask_search_companies", searchTerm="Acme", isActive=True, pageSize=2)
    sent = body_of(route)
    assert sent["MaxRecords"] == 3
    assert {"op": "contains", "field": "companyName", "value": "Acme"} in sent["Filter"]
    assert {"op": "eq", "field": "isActive", "value": True} in sent["Filter"]
    assert out["count"] == 2 and out["has_more"] is True
    assert out["items"][0] == {"id": 1, "companyName": "Acme 1"}  # nulls dropped


@respx.mock
async def test_page_two_skips_by_id_cursor(call):
    route = respx.post(f"{ZONE}/Companies/query").mock(
        side_effect=[
            httpx.Response(200, json={"items": [{"id": 3}, {"id": 7}]}),
            httpx.Response(200, json={"items": [{"id": 9, "companyName": "C"}]}),
        ]
    )
    out = await call("autotask_search_companies", page=2, pageSize=2)
    first = json.loads(route.calls[0].request.content)
    second = json.loads(route.calls[1].request.content)
    assert first["IncludeFields"] == ["id"] and first["MaxRecords"] == 2
    assert {"op": "gt", "field": "id", "value": 7} in second["Filter"]
    assert out["items"] == [{"id": 9, "companyName": "C"}] and out["has_more"] is False


@respx.mock
async def test_page_size_is_capped(call):
    route = respx.post(f"{ZONE}/Tickets/query").mock(return_value=httpx.Response(200, json={"items": []}))
    out = await call("autotask_search_tickets", pageSize=500)
    assert body_of(route)["MaxRecords"] == 201
    assert out["page_size"] == 200


@respx.mock
async def test_search_tickets_defaults_to_open_and_unassigned(call):
    route = respx.post(f"{ZONE}/Tickets/query").mock(return_value=httpx.Response(200, json={"items": []}))
    await call("autotask_search_tickets", unassigned=True, queueID=5)
    filters = body_of(route)["Filter"]
    assert {"op": "noteq", "field": "status", "value": 5} in filters
    assert {"op": "notExist", "field": "assignedResourceID"} in filters
    assert {"op": "eq", "field": "queueID", "value": 5} in filters


@respx.mock
@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (401, {}, "unauthorized", False),
        (403, {"errors": ["no access"]}, "unauthorized", False),
        (404, {}, "not_found", False),
        (400, {"errors": ["bad"]}, "invalid_argument", False),
        (500, {"errors": ["dueDateTime is required"]}, "invalid_argument", False),
        (503, {}, "upstream_error", True),
    ],
)
async def test_error_mapping(call, status, body, code, retryable):
    respx.get(f"{ZONE}/Tickets/9").mock(return_value=httpx.Response(status, json=body))
    out = await call("autotask_get_ticket_details", ticketID=9)
    assert out["error"]["code"] == code
    assert out["error"]["retryable"] is retryable


@respx.mock
async def test_null_item_is_not_found(call):
    respx.get(f"{ZONE}/Tickets/9").mock(return_value=httpx.Response(200, json={"item": None}))
    out = await call("autotask_get_ticket_details", ticketID=9)
    assert out["error"]["code"] == "not_found"


@respx.mock
async def test_retries_rate_limit_then_succeeds(call):
    route = respx.get(f"{ZONE}/ThresholdInformation").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(200, json={})]
    )
    out = await call("autotask_test_connection")
    assert out["status"] == "ok" and route.call_count == 2


@respx.mock
async def test_business_rule_500_is_not_retried(call):
    route = respx.post(f"{ZONE}/Tickets").mock(
        return_value=httpx.Response(500, json={"errors": ["dueDateTime is required"]})
    )
    out = await call("autotask_create_ticket", companyID=1, title="t", description="d")
    assert route.call_count == 1
    assert out["error"]["code"] == "invalid_argument" and "dueDateTime" in out["error"]["message"]


@respx.mock
async def test_create_is_not_retried_on_plain_5xx(call):
    route = respx.post(f"{ZONE}/Tickets").mock(return_value=httpx.Response(502))
    out = await call("autotask_create_ticket", companyID=1, title="t", description="d")
    assert route.call_count == 1 and out["error"]["code"] == "upstream_error"


@respx.mock
async def test_create_ticket_defaults_and_role_resolution(call):
    respx.post(f"{ZONE}/ResourceRoles/query").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 1, "resourceID": 4, "roleID": 30, "isActive": True}]})
    )
    respx.post(f"{ZONE}/Roles/query").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 30, "name": "Help Desk", "isActive": True}]})
    )
    tickets = respx.post(f"{ZONE}/Tickets").mock(return_value=httpx.Response(200, json={"itemId": 77}))
    extra = respx.post(f"{ZONE}/TicketAdditionalContacts").mock(return_value=httpx.Response(200, json={"itemId": 1}))
    out = await call(
        "autotask_create_ticket",
        companyID=1,
        title="Printer",
        description="Jammed",
        assignedResourceID=4,
        ticketAdditionalContacts=[12],
    )
    sent = body_of(tickets)
    assert sent["status"] == 1 and sent["assignedResourceRoleID"] == 30
    assert body_of(extra) == {"ticketID": 77, "contactID": 12}
    assert out["id"] == 77 and out["additionalContacts"] == [{"contactID": 12, "added": True}]


@respx.mock
async def test_role_resolution_reports_several_roles(call):
    respx.post(f"{ZONE}/ResourceRoles/query").mock(
        return_value=httpx.Response(
            200, json={"items": [{"resourceID": 4, "roleID": 30, "isActive": True}, {"resourceID": 4, "roleID": 31}]}
        )
    )
    respx.post(f"{ZONE}/Roles/query").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 30, "name": "Help Desk"}, {"id": 31, "name": "Field"}]})
    )
    out = await call("autotask_update_ticket", ticketId=5, assignedResourceID=4)
    assert out["error"]["code"] == "invalid_argument"
    assert "Help Desk" in out["error"]["message"] and "Field" in out["error"]["message"]


@respx.mock
async def test_create_contact_falls_back_to_company_route_on_html_404(call):
    top = respx.post(f"{ZONE}/Contacts").mock(
        return_value=httpx.Response(404, text="<html>Not Found</html>", headers={"content-type": "text/html"})
    )
    child = respx.post(f"{ZONE}/Companies/3/Contacts").mock(return_value=httpx.Response(200, json={"itemId": 55}))
    out = await call("autotask_create_contact", companyID=3, firstName="Jane", lastName="Doe")
    assert top.call_count == 1 and out == {"id": 55, "created": True, "entity": "Contacts"}
    assert body_of(child)["isActive"] == 1


@respx.mock
async def test_update_contact_falls_back_via_parent_lookup(call):
    respx.patch(f"{ZONE}/Contacts").mock(return_value=httpx.Response(405))
    respx.get(f"{ZONE}/Contacts/8").mock(return_value=httpx.Response(200, json={"item": {"id": 8, "companyID": 3}}))
    child = respx.patch(f"{ZONE}/Companies/3/Contacts").mock(return_value=httpx.Response(200, json={"itemId": 8}))
    out = await call("autotask_update_contact", id=8, isActive=False, title="CTO")
    assert body_of(child) == {"id": 8, "title": "CTO", "isActive": 0}
    assert out["updated"] is True


@respx.mock
async def test_create_contact_does_not_fall_back_on_validation_error(call):
    respx.post(f"{ZONE}/Contacts").mock(return_value=httpx.Response(500, json={"errors": ["Email invalid"]}))
    child = respx.post(f"{ZONE}/Companies/3/Contacts")
    out = await call("autotask_create_contact", companyID=3, firstName="J", lastName="D")
    assert out["error"]["code"] == "invalid_argument" and child.call_count == 0


@respx.mock
async def test_search_contacts_hides_udfs_by_default(call):
    respx.post(f"{ZONE}/Contacts/query").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": 1, "userDefinedFields": [{"name": "x", "value": "1"}]}]}
        )
    )
    out = await call("autotask_search_contacts", searchTerm="jane")
    assert "userDefinedFields" not in out["items"][0]
    out = await call("autotask_search_contacts", includeUserDefinedFields=True)
    assert out["items"][0]["userDefinedFields"] == [{"name": "x", "value": "1"}]


@respx.mock
async def test_search_billing_codes_adds_use_type_label(call):
    route = respx.post(f"{ZONE}/BillingCodes/query").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 9, "name": "Remote", "useType": 1, "isActive": True}]})
    )
    respx.get(f"{ZONE}/BillingCodes/entityInformation/fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "fields": [{"name": "useType", "picklistValues": [{"value": "1", "label": "General Allocation Code"}]}]
            },
        )
    )
    out = await call("autotask_search_billing_codes", useType=1)
    assert {"op": "eq", "field": "isActive", "value": True} in body_of(route)["Filter"]
    assert out["items"][0]["useTypeLabel"] == "General Allocation Code"


@respx.mock
async def test_field_info_flags_reference_fields(call):
    respx.get(f"{ZONE}/Tickets/entityInformation/fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "fields": [
                    {"name": "billingCodeID", "isReference": True, "referenceEntityType": "BillingCode"},
                    {"name": "status", "isPickList": True, "picklistValues": [{"value": "1", "label": "New"}]},
                ]
            },
        )
    )
    out = await call("autotask_get_field_info", entityType="Tickets", fieldName="billingcodeid")
    assert "autotask_search_billing_codes" in out["fields"][0]["note"]


@respx.mock
async def test_list_ticket_statuses(call):
    respx.get(f"{ZONE}/Tickets/entityInformation/fields").mock(
        return_value=httpx.Response(
            200,
            json={
                "fields": [
                    {
                        "name": "status",
                        "picklistValues": [
                            {"value": "1", "label": "New", "isActive": True},
                            {"value": "9", "label": "Old", "isActive": False},
                        ],
                    }
                ]
            },
        )
    )
    out = await call("autotask_list_ticket_statuses")
    assert [v["label"] for v in out["items"]] == ["New"]


@respx.mock
async def test_regular_time_uses_internal_billing_code(call):
    codes = respx.post(f"{ZONE}/BillingCodes/query").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 29, "name": "Internal Meeting"}]})
    )
    entry = respx.post(f"{ZONE}/TimeEntries").mock(return_value=httpx.Response(200, json={"itemId": 100}))
    out = await call(
        "autotask_create_time_entry",
        resourceID=4,
        category="Internal Meeting",
        dateWorked="2026-01-05",
        hoursWorked=1.5,
        summaryNotes="",
    )
    assert {"op": "eq", "field": "useType", "value": 3} in body_of(codes)["Filter"]
    sent = body_of(entry)
    assert sent["billingCodeID"] == 29 and "roleID" not in sent and sent["summaryNotes"] == ""
    assert out["id"] == 100


@respx.mock
async def test_ticket_time_uses_parent_role(call):
    respx.get(f"{ZONE}/Tickets/5").mock(
        return_value=httpx.Response(
            200, json={"item": {"id": 5, "assignedResourceID": 4, "assignedResourceRoleID": 31}}
        )
    )
    respx.post(f"{ZONE}/ResourceRoles/query").mock(
        return_value=httpx.Response(
            200, json={"items": [{"resourceID": 4, "roleID": 30}, {"resourceID": 4, "roleID": 31}]}
        )
    )
    respx.post(f"{ZONE}/Roles/query").mock(return_value=httpx.Response(200, json={"items": [{"id": 30}, {"id": 31}]}))
    entry = respx.post(f"{ZONE}/TimeEntries").mock(return_value=httpx.Response(200, json={"itemId": 1}))
    await call(
        "autotask_create_time_entry", ticketID=5, resourceID=4, dateWorked="2026-01-05", hoursWorked=1, summaryNotes="x"
    )
    assert body_of(entry)["roleID"] == 31 and body_of(entry)["ticketID"] == 5


@respx.mock
async def test_assign_least_loaded_picks_lowest_count(call):
    respx.post(f"{ZONE}/Tickets/query/count").mock(
        side_effect=[httpx.Response(200, json={"queryCount": 4}), httpx.Response(200, json={"queryCount": 1})]
    )
    patch = respx.patch(f"{ZONE}/Tickets").mock(return_value=httpx.Response(200, json={"itemId": 70}))
    out = await call(
        "autotask_assign_least_loaded_resource",
        technicians=[{"resourceID": 1, "roleID": 10}, {"resourceID": 2, "roleID": 20}],
        status=1,
        queueIDs=[8],
        ticketID=70,
    )
    assert body_of(patch) == {"id": 70, "assignedResourceID": 2, "assignedResourceRoleID": 20}
    assert out["assignedResourceID"] == 2 and out["created"] is False


async def test_assign_least_loaded_validates_arguments(call):
    out = await call("autotask_assign_least_loaded_resource", technicians=[{"resourceID": 1, "roleID": 2}], status=1)
    assert out["error"]["code"] == "invalid_argument"
    out = await call(
        "autotask_assign_least_loaded_resource",
        technicians=[{"resourceID": 1, "roleID": 2}],
        status=1,
        createTicket={"companyID": 1, "title": "t", "description": "d"},
    )
    assert "exactly one queue" in out["error"]["message"]


@respx.mock
async def test_get_ticket_attachment_strips_large_data(call):
    respx.get(f"{ZONE}/TicketAttachments/3").mock(
        return_value=httpx.Response(200, json={"item": {"id": 3, "parentID": 9, "title": "a.png", "data": "A" * 5000}})
    )
    out = await call(
        "autotask_get_ticket_attachment", ticketId=9, attachmentId=3, includeData=True, maxInlineBase64Bytes=2000
    )
    assert "data" not in out and "dataOmittedReason" in out
    out = await call("autotask_get_ticket_attachment", ticketId=9, attachmentId=3, includeData=True)
    assert out["data"] == "A" * 5000
    wrong = await call("autotask_get_ticket_attachment", ticketId=10, attachmentId=3, includeData=True)
    assert wrong["error"]["code"] == "not_found"


@respx.mock
async def test_create_ticket_attachment_checks_size_and_base64(call):
    out = await call("autotask_create_ticket_attachment", ticketId=1, title="x", data="not base64!")
    assert out["error"]["code"] == "invalid_argument"
    big = base64.b64encode(b"0" * (3 * 1024 * 1024 + 1)).decode()
    out = await call("autotask_create_ticket_attachment", ticketId=1, title="x", data=big)
    assert "at most" in out["error"]["message"]
    route = respx.post(f"{ZONE}/Tickets/1/Attachments").mock(return_value=httpx.Response(200, json={"itemId": 4}))
    out = await call(
        "autotask_create_ticket_attachment", ticketId=1, title="a.txt", data=base64.b64encode(b"hi").decode()
    )
    assert body_of(route)["attachmentType"] == "FILE_ATTACHMENT" and out["sizeBytes"] == 2


@respx.mock
async def test_delete_charge_uses_child_route(call):
    route = respx.delete(f"{ZONE}/Tickets/5/Charges/6").mock(return_value=httpx.Response(200, json={"itemId": 6}))
    out = await call("autotask_delete_ticket_charge", ticketId=5, chargeId=6)
    assert route.call_count == 1 and out["deleted"] is True


@respx.mock
async def test_ticket_history_sends_only_ticket_filter(call):
    route = respx.post(f"{ZONE}/TicketHistory/query").mock(return_value=httpx.Response(200, json={"items": []}))
    await call("autotask_search_ticket_history", ticketId=5)
    assert body_of(route)["Filter"] == [{"op": "eq", "field": "ticketID", "value": 5}]


@respx.mock
async def test_raw_request(call):
    route = respx.get(f"{ZONE}/Companies/175").mock(return_value=httpx.Response(200, json={"item": {"id": 175}}))
    out = await call("autotask_raw_request", method="get", path="/v1.0/Companies/175", queryParams={"x": True})
    assert out == {"item": {"id": 175}} and route.calls.last.request.url.params["x"] == "true"
    for bad in ("https://example.com/x", "/Companies/../../x", "/Companies?x=1"):
        out = await call("autotask_raw_request", method="GET", path=bad)
        assert out["error"]["code"] == "invalid_argument", bad


async def test_meta_tools(call):
    cats = await call("autotask_list_categories")
    assert any(c["name"] == "tickets" for c in cats["categories"])
    tools = await call("autotask_list_category_tools", category="financial")
    assert any(t["name"] == "autotask_search_billing_codes" for t in tools["tools"])
    routed = await call("autotask_router", intent="log 2 hours on ticket 12345")
    first = routed["suggestions"][0]
    assert first["tool"] == "autotask_create_time_entry"
    assert first["arguments"]["hoursWorked"] == 2.0 and first["arguments"]["ticketID"] == 12345
    bad = await call("autotask_execute_tool", toolName="autotask_execute_tool")
    assert bad["error"]["code"] == "invalid_argument"


@respx.mock
async def test_execute_tool_dispatches(call):
    respx.get(f"{ZONE}/ThresholdInformation").mock(return_value=httpx.Response(200, json={}))
    out = await call("autotask_execute_tool", toolName="autotask_test_connection", arguments={})
    assert out["status"] == "ok"
    out = await call("autotask_execute_tool", toolName="autotask_get_ticket_details", arguments={})
    assert out["error"]["code"] == "invalid_argument"
