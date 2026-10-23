# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from autotask_mcp import credentials
from autotask_mcp.config import Settings
from autotask_mcp.server import create_mcp

ZONE = "https://webservices99.autotask.net/ATServicesRest/v1.0"


@pytest.fixture
def settings() -> Settings:
    # Keep retries fast in tests.
    return Settings(max_retries=2, call_budget_seconds=10)


@pytest.fixture
def mcp(settings):
    return create_mcp(settings)


def make_creds(**overrides) -> credentials.Credentials:
    values = dict(
        username="api-user@example.com",
        secret="YOUR_API_SECRET",
        integration_code="YOUR_INTEGRATION_CODE",
        api_url="https://webservices99.autotask.net/ATServicesRest/",
    )
    values.update(overrides)
    return credentials.Credentials(**values)


@pytest.fixture
def creds():
    token = credentials._current.set(make_creds())
    yield
    credentials._current.reset(token)


@pytest.fixture
def call(mcp):
    async def _call(tool: str, /, **args):
        result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return json.loads(blocks[0].text)

    return _call
