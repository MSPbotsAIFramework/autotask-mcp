# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for tool handlers.

Tools are declared with :func:`tool`: a name, a description, annotations and a list of
parameters (:func:`Req` / :func:`Opt`). The parameter list becomes the tool's input schema,
and the handler receives an :class:`AutotaskClient` bound to this request's credentials plus
the validated arguments as an :class:`Args` object.
"""

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .. import _json
from ..api import ApiError, AutotaskClient, item_id
from ..config import API_KEY_HEADER, API_SECRET_HEADER, Settings
from ..credentials import current

log = logging.getLogger("autotask_mcp")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)

DELETE_WARNING = "Permanent and irreversible: confirm with the user before calling."


class ToolInputError(ValueError):
    """Raised by handlers for arguments Autotask would reject anyway."""


class Args:
    """Validated tool arguments with attribute access; unset optional values are ``None``."""

    def __init__(self, values: dict[str, Any]):
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._values.get(name)

    def get(self, name: str, default: Any = None) -> Any:
        value = self._values.get(name)
        return default if value is None else value

    def fields(self, mapping: dict[str, str] | list[str] | tuple[str, ...]) -> dict[str, Any]:
        """Set values only, renamed to Autotask field names (``{"param": "apiField"}`` or a list of shared names)."""
        pairs = mapping.items() if isinstance(mapping, dict) else ((n, n) for n in mapping)
        return {api: self._values[param] for param, api in pairs if self._values.get(param) is not None}


@dataclass(frozen=True)
class Param:
    name: str
    type: Any
    description: str
    required: bool = False


def Req(name: str, type_: Any, description: str) -> Param:  # noqa: N802 - reads like a type
    return Param(name, type_, description, True)


def Opt(name: str, type_: Any, description: str) -> Param:  # noqa: N802
    return Param(name, type_, description, False)


PAGE = Opt("page", int, "Page number, starting at 1 (default 1).")
PAGE_SIZE = Opt("pageSize", int, f"Results per page (default {DEFAULT_PAGE_SIZE}, max {MAX_PAGE_SIZE}).")


def paging(a: Args, default: int = DEFAULT_PAGE_SIZE) -> tuple[int, int]:
    size = min(max(int(a.get("pageSize", default)), 1), MAX_PAGE_SIZE)
    page = max(int(a.get("page", 1)), 1)
    return page, size


Handler = Callable[[AutotaskClient, Args], Awaitable[Any]]


async def run(settings: Settings, handler: Callable[[AutotaskClient], Awaitable[Any]]) -> str:
    """Execute ``handler`` with a client bound to this request's credentials.

    Always returns a string: the JSON result, or an error envelope.
    """
    creds = current()
    if creds is None:
        return _json.error(
            "not_configured",
            f"No Autotask credentials. Send the {API_KEY_HEADER} and {API_SECRET_HEADER} headers.",
        )
    try:
        async with AutotaskClient(creds, settings) as client:
            result = await handler(client)
    except ApiError as exc:
        return _json.error(exc.code, exc.message, exc.retryable)
    except ToolInputError as exc:
        return _json.error("invalid_argument", str(exc))
    except Exception:  # noqa: BLE001 - tools must never raise
        log.exception("unexpected error in tool handler")
        return _json.error("upstream_error", "Unexpected error while calling Autotask.", True)
    return result if isinstance(result, str) else _json.dump(result)


def tool(
    mcp: FastMCP,
    settings: Settings,
    name: str,
    description: str,
    annotations: ToolAnnotations,
    *params: Param,
    title: str | None = None,
    local: bool = False,
) -> Callable[[Handler], Handler]:
    """Register ``handler`` as an MCP tool with the given parameters.

    ``local=True`` runs the handler without Autotask credentials (client is ``None``); used by the
    meta tools that only describe or dispatch to other tools.
    """

    def decorator(handler: Handler) -> Handler:
        async def fn(**kwargs: Any) -> str:
            args = Args(kwargs)
            if local:
                try:
                    result = await handler(None, args)  # type: ignore[arg-type]
                except ToolInputError as exc:
                    return _json.error("invalid_argument", str(exc))
                except Exception:  # noqa: BLE001
                    log.exception("unexpected error in local tool")
                    return _json.error("upstream_error", "Unexpected error.", True)
                return result if isinstance(result, str) else _json.dump(result)

            async def bound(client: AutotaskClient) -> Any:
                return await handler(client, args)

            return await run(settings, bound)

        signature = []
        for p in params:
            annotation = Annotated[p.type if p.required else p.type | None, Field(description=p.description)]
            default = inspect.Parameter.empty if p.required else None
            signature.append(
                inspect.Parameter(p.name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation)
            )
        fn.__signature__ = inspect.Signature(signature, return_annotation=str)  # type: ignore[attr-defined]
        fn.__name__ = name
        fn.__doc__ = description
        mcp.add_tool(
            fn, name=name, title=title, description=description, annotations=annotations, structured_output=False
        )
        return handler

    return decorator


# ---- common Autotask operations --------------------------------------------


async def search(
    c: AutotaskClient,
    entity: str,
    filters: list[dict[str, Any]],
    a: Args,
    *,
    default_size: int = DEFAULT_PAGE_SIZE,
    include_fields: list[str] | None = None,
    drop: set[str] | None = None,
) -> dict[str, Any]:
    page, size = paging(a, default_size)
    result = await c.search(entity, filters, page, size, include_fields)
    if drop:
        result["items"] = [{k: v for k, v in i.items() if k not in drop} for i in result["items"]]
    return result


def require_any(values: dict[str, Any], what: str = "field to change") -> None:
    if not any(k != "id" for k in values):
        raise ToolInputError(f"Pass at least one {what}.")


async def create(c: AutotaskClient, entity: str, body: dict[str, Any], child: str | None = None) -> dict[str, Any]:
    """POST the record to ``/{entity}``; fall back to the parent-scoped ``child`` URL on 404/405."""
    paths = [f"/{entity}"] + ([child] if child else [])
    payload = await c.first_route("POST", paths, body)
    return {"id": item_id(payload), "created": True, "entity": entity}


async def update(c: AutotaskClient, entity: str, body: dict[str, Any], child: str | None = None) -> dict[str, Any]:
    """PATCH the record (``id`` in the body); fall back to the parent-scoped ``child`` URL on 404/405."""
    paths = [f"/{entity}"] + ([child] if child else [])
    payload = await c.first_route("PATCH", paths, body)
    return {"id": item_id(payload) or body.get("id"), "updated": True, "entity": entity, "fields": sorted(body)}


async def update_via_parent(
    c: AutotaskClient, entity: str, body: dict[str, Any], child_path: Callable[[], Awaitable[str]]
) -> dict[str, Any]:
    """PATCH ``/{entity}``; on 404/405 look up the parent and PATCH the parent-scoped URL instead."""
    try:
        return await update(c, entity, body)
    except ApiError as exc:
        if exc.status not in (404, 405):
            raise
    payload = await c.first_route("PATCH", [await child_path()], body)
    return {"id": item_id(payload) or body.get("id"), "updated": True, "entity": entity, "fields": sorted(body)}


async def remove(c: AutotaskClient, paths: list[str], record_id: int, entity: str) -> dict[str, Any]:
    await c.first_route("DELETE", paths)
    return {"id": record_id, "deleted": True, "entity": entity}


def belongs(item: dict[str, Any], field: str, parent_id: int, what: str) -> dict[str, Any]:
    """Make sure a child record belongs to the parent the caller named."""
    if item.get(field) is not None and int(item[field]) != int(parent_id):
        raise ApiError("not_found", f"{what} does not belong to {field} {parent_id}.", False, 404)
    return item


def title_from(text: str | None, limit: int = 100) -> str:
    """Default note title: the first line of the text, shortened."""
    stripped = (text or "").strip()
    return (stripped.splitlines()[0] if stripped else "Note")[:limit]
