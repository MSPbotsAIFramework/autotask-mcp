# AGENTS.md

Autotask PSA MCP server for the MSPbots Agent Platform. Python 3.12, uv, official `mcp` SDK (FastMCP), httpx, Docker.

## Commands

- `uv sync`: install
- `uv run pytest -q`: tests
- `uv run ruff check . && uv run ruff format --check .`: lint
- `uv run autotask-mcp`: run on 0.0.0.0:8080 (`/mcp`, `/health`)
- `docker build -t autotask-mcp .`

## Layout

- `src/autotask_mcp/server.py`: FastMCP instance, instructions, HTTP app
- `src/autotask_mcp/credentials.py`: reads `X-Api-Key`, `X-Api-Secret`, `X-Integration-Code`, `X-Api-Url` into a per-request ContextVar
- `src/autotask_mcp/api.py`: Autotask HTTP client (zone lookup, retries, error mapping, query / paging helpers)
- `src/autotask_mcp/tools/`: one module per area; `_common.py` has the declarative `tool()` registrar, paging, annotations, `run()`; `_resolve.py` resolves resource and role names
- `tests/fixtures/tools_baseline.json`: tool names / parameters / types the platform already relies on

## Rules

- Credentials only from request headers; never from env, never cached across requests (zone lookup included).
- Middleware only checks that `X-Api-Key` and `X-Api-Secret` are present. Never validate header formats there: the platform probes with placeholder values.
- Stateless (`stateless_http=True`); no module-level mutable state.
- Tools return JSON strings; errors use the envelope in `_json.py`; tools never raise.
- Do not rename tools, remove parameters or add required parameters: agents on the platform depend on them.
  `tests/test_tools.py` enforces this against the baseline.
- Child-entity writes fall back to the parent URL on 404/405 (some zones lack collection routes).
- English only, ASCII only in code. No real credentials, hostnames, tenant or customer data anywhere, including tests and history.
- No third-party branding other than the Autotask product itself.
- Add dependencies with `uv add`; commit `uv.lock`.
- Record changes in `docs/changes/` and releases in `docs/releases/`.
