# 2026-11-16 By-id reads accept the `items` response shape (PRD-22216)

`autotask_get_ticket_attachment` (and `autotask_get_ticket_note_attachment`) returned `not_found` for
attachments that the search tool lists, because the by-id GET parsed only `{"item": {...}}` while
Autotask answers `{"items": [{...}]}`. The shared client helper `AutotaskClient.get_item()` and the
parent-scoped attachment metadata read now both use `single_record()`, which accepts either shape
(for a list it picks the element whose `id` matches, else the first). Every tool that reads one
record by id benefits.

No tool, parameter or response shape changed; `{"item": ...}` answers behave as before. The
ownership check (attachment must belong to the given ticket / note) is unchanged.
