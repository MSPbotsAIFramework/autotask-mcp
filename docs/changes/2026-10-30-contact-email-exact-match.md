# 2026-10-30 Contact exact email match (PRD-21388)

`autotask_search_contacts` gains one optional parameter, `email`. When set, it exact-matches
(`eq`, OR'd) `emailAddress`, `emailAddress2`, or `emailAddress3`, ANDed with the existing
`companyID`/`isActive` filters. Purely additive: omitting `email` reproduces today's behavior
byte-for-byte. The existing `searchTerm` fuzzy match (contains on `firstName`/`lastName`/
`emailAddress` only) is unchanged.

Enables read-only authorization checks (for example PRECICOM's offboarding agent) that need to
find a contact by a non-primary email and read its `userDefinedFields` (already available via the
existing `includeUserDefinedFields` flag) without needing `autotask_raw_request`, which can also
write.

No new tool, no new dependency, no schema change (this service holds no state of its own).
