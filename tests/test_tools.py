# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""tools/list contract: names and parameters must stay compatible with the registered connector."""

import json
from pathlib import Path

from autotask_mcp.tools.meta import CATEGORIES, META_TOOLS

BASELINE = json.loads((Path(__file__).parent / "fixtures" / "tools_baseline.json").read_text())

# A baseline "number" accepts JSON integers too; everything else must keep its JSON type.
COMPATIBLE = {"number": {"number", "integer"}}


async def _tools(mcp):
    return {t.name: t for t in await mcp.list_tools()}


def _json_type(prop: dict) -> str | None:
    if "type" in prop:
        return prop["type"]
    for option in prop.get("anyOf", []):
        if option.get("type") != "null":
            return option.get("type")
    return None


async def test_tool_names_match_baseline(mcp):
    tools = await _tools(mcp)
    assert len(tools) == 111
    assert set(tools) == set(BASELINE)


async def test_parameters_are_backward_compatible(mcp):
    tools = await _tools(mcp)
    for name, expected in BASELINE.items():
        schema = tools[name].inputSchema
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        assert set(expected["params"]) <= set(props), f"{name} lost parameters"
        assert required <= set(expected["required"]), f"{name} gained required parameters"
        for param, old_type in expected["types"].items():
            new_type = _json_type(props[param])
            assert new_type in COMPATIBLE.get(old_type, {old_type}), f"{name}.{param}: {old_type} -> {new_type}"


async def test_descriptions_are_concise_and_ascii(mcp):
    for tool in (await _tools(mcp)).values():
        assert tool.description and len(tool.description) <= 500, tool.name
        assert tool.description.isascii(), tool.name
        for prop in tool.inputSchema.get("properties", {}).values():
            assert prop.get("description", "").isascii(), tool.name


async def test_annotations(mcp):
    tools = await _tools(mcp)
    for name, tool in tools.items():
        if "_delete_" in name:
            assert tool.annotations.destructiveHint is True, name
        if name.startswith(("autotask_search_", "autotask_get_", "autotask_list_")) or name in (
            "autotask_test_connection",
            "autotask_router",
        ):
            assert tool.annotations.readOnlyHint is True, name
        if name.startswith(("autotask_create_", "autotask_update_", "autotask_delete_")):
            assert tool.annotations.readOnlyHint is False, name


async def test_every_tool_is_in_a_category(mcp):
    categorized = [n for _, names in CATEGORIES.values() for n in names]
    assert len(categorized) == len(set(categorized)), "tool listed twice"
    assert set(categorized) | META_TOOLS == set(await _tools(mcp))


async def test_no_agent_id_parameter(mcp):
    # The platform injects its own value into parameters named agent_id.
    for tool in (await _tools(mcp)).values():
        assert "agent_id" not in tool.inputSchema.get("properties", {}), tool.name
