# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Per-request credentials, taken only from request headers.

The gateway sends each tenant's credentials on every request. They live in a
ContextVar for the duration of that request and are never stored anywhere else.

The middleware only checks that the required headers are present. It never
validates their format: the platform probes ``tools/list`` with placeholder
values, which must succeed. Values are validated when a tool calls Autotask.
"""

import contextvars
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import (
    API_KEY_HEADER,
    API_SECRET_HEADER,
    API_URL_HEADER,
    INTEGRATION_CODE_HEADER,
    OPTIONAL_HEADERS,
    REQUIRED_HEADERS,
)


@dataclass(frozen=True)
class Credentials:
    username: str
    secret: str
    integration_code: str | None = None
    api_url: str | None = None

    def __repr__(self) -> str:  # never print secrets
        return f"Credentials(username={self.username!r}, api_url={self.api_url!r})"


_current: contextvars.ContextVar[Credentials | None] = contextvars.ContextVar("autotask_credentials", default=None)


def current() -> Credentials | None:
    return _current.get()


def _reject(missing: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Missing credentials",
            "message": f"Send the Autotask API credentials in the {' and '.join(missing)} header(s).",
            "required_headers": REQUIRED_HEADERS,
            "optional_headers": OPTIONAL_HEADERS,
        },
        status_code=401,
    )


class CredentialMiddleware:
    """Reads the Autotask headers on /mcp requests and binds them to the request context."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        headers = Request(scope).headers
        values = {name: (headers.get(name) or "").strip() for name in (*REQUIRED_HEADERS, *OPTIONAL_HEADERS)}
        missing = [name for name in REQUIRED_HEADERS if not values[name]]
        if missing:
            await _reject(missing)(scope, receive, send)
            return

        creds = Credentials(
            username=values[API_KEY_HEADER],
            secret=values[API_SECRET_HEADER],
            integration_code=values[INTEGRATION_CODE_HEADER] or None,
            api_url=values[API_URL_HEADER] or None,
        )
        token = _current.set(creds)
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
