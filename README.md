# Autotask PSA MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that lets AI agents on the
MSPbots Agent Platform work with Autotask PSA: companies, contacts, tickets and their notes,
checklists, charges, history and attachments, time entries, projects, sales, contracts, billing,
expenses and service calls.

It runs as a stateless HTTP service behind the MSPbots MCP gateway. The gateway sends each
tenant's Autotask credentials as request headers on every call; the server keeps nothing between
requests.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Credentials (request headers)

| Header | Required | Meaning |
|---|---|---|
| `X-Api-Key` | Yes | User name of the Autotask API user (an API-only resource, usually an email address). Sent to Autotask as `UserName`. |
| `X-Api-Secret` | Yes | Secret of that API user. Sent as `Secret`. |
| `X-Integration-Code` | For tool calls | API tracking identifier (integration code). Sent as `ApiIntegrationCode`. The platform injects it. Without it `tools/list` still works and tools return `not_configured`. |
| `X-Api-Url` | No | Zone REST URL, e.g. `https://webservices5.autotask.net/ATServicesRest/`. Must be `https://` on an `*.autotask.net` host. When absent, the server looks the zone up with the official `zoneInformation?user=` endpoint on every tool call (never cached across requests). |

Header names are case-insensitive. A request to `/mcp` without `X-Api-Key` or `X-Api-Secret`
gets `401` with the list of expected headers. The middleware only checks that the required
headers are present: header formats are validated by the tools, so `initialize` and `tools/list`
succeed with any non-empty values (the platform probes with placeholders).

## Tools

| Area | Tools |
|---|---|
| Companies | `autotask_search_companies`, `autotask_create_company`, `autotask_update_company`, `autotask_get_company_site_configuration`, `autotask_update_company_site_configuration`, `autotask_get_company_note`, `autotask_search_company_notes`, `autotask_create_company_note` |
| Contacts | `autotask_search_contacts`, `autotask_create_contact`, `autotask_update_contact` |
| Tickets | `autotask_search_tickets`, `autotask_get_ticket_details`, `autotask_create_ticket`, `autotask_update_ticket`, `autotask_assign_least_loaded_resource` |
| Ticket notes, checklist, charges, history | `autotask_get_ticket_note`, `autotask_search_ticket_notes`, `autotask_create_ticket_note`, `autotask_search_ticket_checklist_items`, `autotask_create_ticket_checklist_item`, `autotask_update_ticket_checklist_item`, `autotask_delete_ticket_checklist_item`, `autotask_get_ticket_charge`, `autotask_search_ticket_charges`, `autotask_create_ticket_charge`, `autotask_update_ticket_charge`, `autotask_delete_ticket_charge`, `autotask_get_ticket_history`, `autotask_search_ticket_history` |
| Attachments | `autotask_get_ticket_attachment`, `autotask_search_ticket_attachments`, `autotask_get_ticket_note_attachment`, `autotask_search_ticket_note_attachments`, `autotask_create_ticket_attachment` |
| Resources and time | `autotask_search_resources`, `autotask_search_resource_roles`, `autotask_create_time_entry`, `autotask_search_time_entries` |
| Projects | `autotask_search_projects`, `autotask_create_project`, `autotask_update_project`, `autotask_get_project_note`, `autotask_search_project_notes`, `autotask_create_project_note`, `autotask_search_tasks`, `autotask_create_task`, `autotask_list_phases`, `autotask_create_phase` |
| Sales and catalog | `autotask_get_opportunity`, `autotask_search_opportunities`, `autotask_create_opportunity`, `autotask_get_quote`, `autotask_search_quotes`, `autotask_create_quote`, `autotask_get_quote_item`, `autotask_search_quote_items`, `autotask_create_quote_item`, `autotask_update_quote_item`, `autotask_delete_quote_item`, `autotask_get_product`, `autotask_search_products`, `autotask_get_service`, `autotask_search_services`, `autotask_get_service_bundle`, `autotask_search_service_bundles` |
| Contracts | `autotask_search_contracts`, `autotask_get_contract`, `autotask_list_expiring_contracts`, `autotask_search_contract_services`, `autotask_search_contract_service_units`, `autotask_search_contract_service_bundles`, `autotask_search_contract_service_bundle_units`, `autotask_get_contract_recurring_lines`, `autotask_create_contract`, `autotask_create_contracts_bulk`, `autotask_update_contract`, `autotask_create_contract_service`, `autotask_update_contract_service` |
| Finance | `autotask_search_invoices`, `autotask_get_invoice_details`, `autotask_search_billing_items`, `autotask_get_billing_item`, `autotask_search_billing_item_approval_levels`, `autotask_search_billing_codes`, `autotask_get_expense_report`, `autotask_search_expense_reports`, `autotask_create_expense_report`, `autotask_create_expense_item` |
| Service calls | `autotask_get_service_call`, `autotask_search_service_calls`, `autotask_create_service_call`, `autotask_update_service_call`, `autotask_delete_service_call`, `autotask_search_service_call_tickets`, `autotask_create_service_call_ticket`, `autotask_delete_service_call_ticket`, `autotask_search_service_call_ticket_resources`, `autotask_create_service_call_ticket_resource`, `autotask_delete_service_call_ticket_resource` |
| Configuration items | `autotask_search_configuration_items` |
| Reference | `autotask_list_queues`, `autotask_list_ticket_statuses`, `autotask_list_ticket_priorities`, `autotask_get_field_info`, `autotask_test_connection`, `autotask_raw_request` |
| Discovery | `autotask_list_categories`, `autotask_list_category_tools`, `autotask_execute_tool`, `autotask_router` |

All 111 tool names and parameters match the previous Autotask connector on the MSPbots Agent
Platform, so existing agents keep working. That compatibility is why this is one server with far
more than 20 tools rather than several smaller ones. Every tool is always listed; the discovery
tools only describe categories, dispatch to another tool by name, or suggest a tool from a plain
text intent, and keep no state.

Behaviour notes:

- Every tool returns a JSON string. Errors use one envelope:
  `{"error": {"code": "...", "message": "...", "retryable": false}}` with `code` one of
  `not_configured`, `unauthorized`, `not_found`, `invalid_argument`, `rate_limited`, `upstream_error`.
- List tools return `{"items", "count", "page_number", "page_size", "has_more"}`. `pageSize`
  defaults to 25 and is capped at 200 (larger values are accepted and capped). Autotask has no
  offset, so `page` > 1 is read by skipping record IDs. Results larger than 20,000 characters are
  cut and flagged with `truncated` / `has_more`. Null fields are left out of results.
- Some zones do not register collection-level write routes (`POST`/`PATCH /Contacts` answers with
  an HTML 404). Writes to child entities fall back to the parent URL (e.g.
  `/Companies/{companyID}/Contacts`, `/Tickets/{id}/Notes`) when the zone answers 404 or 405.
- A ticket's Work Type is `billingCodeID`, a reference to `BillingCodes`, not a picklist:
  `autotask_get_field_info` cannot list it; use `autotask_search_billing_codes` (useType 1 = Work
  Type, 3 = internal time).
- Ticket assignments and ticket/task time entries need a role; it is resolved from the resource's
  roles when unambiguous, otherwise the error names the candidate roles.
- `autotask_search_tickets` without `status` returns open tickets only (status is not Complete).
- Transient failures (429, 5xx, timeouts) are retried with backoff, honouring `Retry-After`.
  Creates are retried only on 429, so a late 5xx cannot create a duplicate. Autotask reports
  business-rule violations as HTTP 500 with an `errors` list; those map to `invalid_argument` and
  are not retried.
- `autotask_get_ticket_attachment` and `autotask_get_ticket_note_attachment` may return file data
  above the 20,000 character limit, up to `maxInlineBase64Bytes`.

## Run locally

```bash
uv sync
uv run autotask-mcp            # listens on 0.0.0.0:8080
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "X-Api-Key: $AUTOTASK_API_USER" -H "X-Api-Secret: $AUTOTASK_API_SECRET" \
  -H "X-Integration-Code: $AUTOTASK_INTEGRATION_CODE" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Environment variables (all optional): `MCP_HTTP_HOST` (default `0.0.0.0`), `MCP_HTTP_PORT`
(default `8080`), `MCP_TRANSPORT` (`http` or `stdio`). Unknown variables are ignored. Credentials
are never read from the environment.

## Docker

```bash
docker build -t autotask-mcp .
docker run --rm -p 8080:8080 autotask-mcp
```

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Code is in `src/autotask_mcp/` (one module per area under `tools/`), tests in `tests/`.
The implementation follows the public Autotask REST API documentation (Autotask online help,
"REST API": authentication, zone lookup, entities, query syntax and entity information).

## License

Copyright 2026 MSPbots.ai. Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).

Autotask is a trademark of its owner. This project is not affiliated with or endorsed by the
owner of Autotask.
