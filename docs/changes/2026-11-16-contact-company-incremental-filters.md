# 2026-11-16 Contact/company `lastActivityAfter` and `phone` filters (PRD-22107)

`autotask_search_contacts` and `autotask_search_companies` gain two optional parameters:

- `lastActivityAfter` (ISO 8601): adds `lastActivityDate >= value`, the same filter and name
  `autotask_search_tickets` already uses. Used by the platform's 15-minute incremental contact sync.
- `phone`: matches the last 4 digits of the digits-only input with `contains` on `phone` and
  `mobilePhone` (contacts, OR'd) or `phone` (companies). Autotask phones are free text, so the last
  four digits are the longest substring that survives formatting. Used by the platform's live
  caller-ID lookup, which compares the full number client-side.

Purely additive: omitting both reproduces today's request byte-for-byte. No new tool, no new
dependency, no schema change.

Not verified against a live Autotask zone: whether an edit to a phone number or the active flag
bumps `lastActivityDate` on Contacts/Companies (see the platform ticket's risks).
