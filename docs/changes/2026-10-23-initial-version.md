# 2026-10-23 Initial version

First release of the MSPbots Autotask PSA MCP server, written from the public Autotask REST API
documentation. It replaces the previous connector implementation.

- 111 tools; names and parameters are compatible with the previous Autotask connector on the
  platform (enforced by `tests/test_tools.py`). No new required parameters.
- Credentials: `X-Api-Key` (API user name) and `X-Api-Secret` (required), `X-Integration-Code`
  (required by tools, optional for `tools/list`), `X-Api-Url` (optional zone URL; looked up per
  tool call via `zoneInformation?user=` when absent). The middleware only checks presence.
- Plain httpx client; no vendor SDK or private package.

## Behaviour differences from the previous connector

- `pageSize` is capped at 200 (was up to 500 on some tools); larger values are capped, not
  rejected. Default page size is 25. Pages beyond the first are read by skipping record IDs.
- Result shape for lists is `{items, count, page_number, page_size, has_more}`; null fields are
  left out. Results above 20,000 characters are truncated and flagged (attachment data excepted).
- No in-process serialization in `autotask_assign_least_loaded_resource`: the server is stateless,
  so concurrent calls for the same team can pick the same technician. Loads are counted with
  `query/count`; the ticket being reassigned does not count toward its current assignee.
- `autotask_router` is keyword based and only suggests tools and arguments read from the text.
- `autotask_execute_tool` refuses to call the discovery tools.
- `autotask_update_project`: `assignedResourceID` is used as `projectLeadResourceID` when that is
  not given; `assignedResourceRoleID` is accepted but ignored (projects have no role field);
  `departmentID` is sent as `department`.
- `autotask_create_project`: `startDate`/`endDate`/`estimatedHours` are sent as
  `startDateTime`/`endDateTime`/`estimatedTime`.
- `autotask_create_ticket` defaults `status` to 1 (New); priority, queue and due date are not
  defaulted. Additional contacts are added after creation and reported per contact.
- Ticket and project notes without a title use the first line of the description.
- `autotask_create_time_entry`: Regular Time looks up `category` among active internal billing
  codes (useType 3). Ticket/task time resolves the role from the parent assignment or the
  resource's only active role.
- `autotask_get_ticket_details` with `fullDetails=true` adds the latest 20 notes and time entries.
- No ticket card UI resource (`_meta.ui`), no read-only mode, no resource impersonation header,
  no 401 retry with a fresh zone lookup.
- Writes to child entities (contacts, notes, checklist items, charges, quote items, contract
  services, tasks, phases, service call tickets and resources, site configuration) fall back to
  the parent URL on 404/405. Deletes of ticket charges, checklist items and quote items use the
  parent URL first.

## Not verified against a live tenant

No Autotask account was used. Field names and child URLs follow the documentation; the fallback
URLs for site configuration, ticket additional contacts and expense items, the
`CompanySiteConfigurations` update shape, and the ascending-ID ordering that paging relies on
should be checked on INT.
