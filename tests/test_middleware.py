# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import pytest
from starlette.testclient import TestClient

from autotask_mcp import credentials
from autotask_mcp.config import Settings
from autotask_mcp.server import create_app

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
INIT = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PLACEHOLDERS = {
    "X-Api-Key": "probe-placeholder",
    "X-Api-Secret": "probe-placeholder",
    "X-Integration-Code": "probe-placeholder",
    "X-Api-Url": "probe-placeholder",
}


@pytest.fixture
def client():
    with TestClient(create_app(Settings())) as c:
        yield c


def test_health_needs_no_credentials(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_missing_headers_is_401(client):
    r = client.post("/mcp", json=LIST, headers=HEADERS)
    assert r.status_code == 401
    body = r.json()
    assert body["required_headers"] == ["X-Api-Key", "X-Api-Secret"]
    assert "X-Integration-Code" in body["optional_headers"] and "X-Api-Url" in body["optional_headers"]


def test_missing_secret_is_401(client):
    r = client.post("/mcp", json=LIST, headers={**HEADERS, "X-Api-Key": "user@example.com"})
    assert r.status_code == 401
    assert "X-Api-Secret" in r.json()["message"]


def test_placeholder_values_are_accepted(client):
    # The platform probes with placeholder values; formats are not validated in middleware.
    h = {**HEADERS, **PLACEHOLDERS}
    assert client.post("/mcp", json=INIT, headers=h).status_code == 200
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 200
    assert len(r.json()["result"]["tools"]) == 111


def test_integration_code_and_url_are_optional_in_middleware(client):
    h = {**HEADERS, "x-api-key": "k", "x-api-secret": "s"}
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 200


def test_tool_call_with_missing_integration_code_returns_not_configured(client):
    h = {**HEADERS, "x-api-key": "k", "x-api-secret": "s"}
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "autotask_test_connection", "arguments": {}},
    }
    r = client.post("/mcp", json=call, headers=h)
    assert r.status_code == 200
    assert '"not_configured"' in r.json()["result"]["content"][0]["text"]


def test_credentials_do_not_leak_between_requests():
    assert credentials.current() is None


def test_credentials_repr_hides_secret():
    c = credentials.Credentials(username="u@example.com", secret="YOUR_API_SECRET", integration_code="x")
    assert "YOUR_API_SECRET" not in repr(c)
