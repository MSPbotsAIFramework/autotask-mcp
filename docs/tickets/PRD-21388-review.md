# PRD-21388 · Code review

## Round 1 · 2026-10-30 · reviewed dev/PRD-21388 @ 2ddbcc8 (base main@1fadd54)

Verdict: changes requested

### Findings

1. [must-fix] docs/tickets/PRD-21388.md:181 — the Self-test section's own "Chinese-character scan" bullet quotes the removed tags literally (`[改]`, `[无改动需要]`, `[新增, 开发环节]`), which reintroduces Chinese characters into the file. Re-running the exact command cited in that same bullet (`grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`) against the current commit produces one hit on this line — confirmed by running it during this review. This violates the repo's own English-only rule (`AGENTS.md:30`, "English only, ASCII only in code") and the explicit MCP review criterion in `references/mcp-track.md` §4.3 ("仓库里没有中文"), and makes the bullet's own claim ("no output after fixing...") false for the commit it describes. Fix: rewrite the bullet so it does not reproduce the Chinese characters verbatim (e.g. describe the fix without quoting the removed text, or use escaped/transliterated references), then re-run the scan and confirm zero output.

### Verified during this review (not findings, recorded for the next reviewer)

- `uv run pytest -q`: 65 passed, 0 failed, 1 pre-existing warning (matches Self-test claim).
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 33 files already formatted.
- Local server smoke test (`uv run autotask-mcp`): `/health` → 200 (confirmed independently on port 8080).
- README "MSPbots Connector" block (`README.md:12-83`) diffed byte-for-byte against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — identical.
- `docs/tickets/PRD-21388.ac.json` validated with `ticket_store.py validate`: 11 cases, structurally OK. TC-ATC-010 correctly recorded as `untested` (needs a real vendor account, not a blocker per `references/mcp-track.md` §3).
- `tests/test_tools.py::test_parameters_are_backward_compatible` confirms the new optional `email` parameter does not break the 111-tool baseline contract (subset check).
- `mbp.py mcplock info --repo autotask-mcp`: `locked: false` — dev-lock correctly released.
- Diff scope (`git diff origin/main...HEAD --stat`): `README.md`, `docs/changes/2026-10-30-contact-email-exact-match.md`, `docs/tickets/PRD-21388.ac.json`, `docs/tickets/PRD-21388.md`, `src/autotask_mcp/tools/contacts.py`, `tests/test_handlers.py` — matches the tech design's change list, no out-of-scope files touched.
- `src/autotask_mcp/tools/contacts.py:42-85` — the new `email` parameter follows the existing `any_of`/`op`/`build` pattern used elsewhere in this file and in `companies.py`/`time_entries.py`/`tickets.py`; ANDed correctly with `companyID`/`isActive`; independent of `searchTerm` as designed; no change to `UPDATE_FIELDS`, `create_contact`, or `update_contact`.
