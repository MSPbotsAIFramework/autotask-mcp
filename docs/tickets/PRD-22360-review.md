# PRD-22360 · Code review

Status: frozen @ 3632a82

## Round 1 · 2026-11-23 · reviewed dev/PRD-22360 @ 3632a82 (base f84c43c)

Verdict: approved

### Findings
1. [suggestion] src/autotask_mcp/tools/attachments.py:62 — `asyncio.wait_for(asyncio.to_thread(...))` stops waiting after 20 s but cannot cancel the parser thread, so a pathological PDF can keep a worker busy past the timeout. The 10 MiB and 100-page caps bound this; consider a process-level limit later.
2. [suggestion] src/autotask_mcp/pdf_text.py:98 — label detection for widgets without `/TU` or a meaningful name relies on position heuristics; table fidelity on the real checklist layout is unverified (stated in the design). Re-check on INT with the fixtures.

### Checks
- Credentials: unchanged (Header only); PDF content and names are not logged (only the exception type).
- Tool contract: new optional params `includeRawPdf`, `maxTextChars` added to both attachment tools; baseline fixture and tests updated; non-PDF path unchanged.
- Gates re-run in the review: pytest 93 passed, ruff clean; no non-ASCII CJK text in the repo diff.
- Scope matches the technical design; no unrelated changes.
