# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Thin async client for the Autotask PSA REST API.

Reference: Autotask REST API documentation (autotask.net online help, "REST API").
- Base URL per zone: ``https://webservicesN.autotask.net/ATServicesRest/v1.0``; the zone is found
  with ``GET zoneInformation?user=<API user name>``.
- Auth headers ``UserName``, ``Secret`` and ``ApiIntegrationCode`` on every call.
- Queries: ``POST /{Entity}/query`` with ``{"MaxRecords", "IncludeFields", "Filter": [...]}``;
  at most 500 records per call. ``POST /{Entity}/query/count`` returns ``queryCount``.
- Single record: ``GET /{Entity}/{id}`` -> ``{"item": {...}}``. Create: ``POST /{Entity}`` -> ``{"itemId"}``.
  Update: ``PATCH /{Entity}`` with ``id`` in the body. Child entities also have parent URLs such as
  ``/Tickets/{id}/Notes``.
- Picklists and field metadata: ``GET /{Entity}/entityInformation/fields``.
- Errors come back as ``{"errors": ["..."]}``. Business-rule violations are often HTTP 500.
"""

import asyncio
import email.utils
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import (
    ALLOWED_HOST_SUFFIX,
    API_URL_HEADER,
    INTEGRATION_CODE_HEADER,
    REST_PATH,
    ZONE_LOOKUP_URL,
    Settings,
)
from .credentials import Credentials

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF = 20.0
MAX_RECORDS = 500  # Autotask hard limit per query call
USER_AGENT = "mspbots-autotask-mcp/1.0"


@dataclass
class ApiError(Exception):
    code: str
    message: str
    retryable: bool = False
    status: int | None = None

    def __str__(self) -> str:
        return self.message


def normalize_base_url(value: str, source: str) -> str:
    """Return ``https://<host>/ATServicesRest/v1.0`` for a zone URL, or raise ``ApiError``."""
    text = (value or "").strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(ALLOWED_HOST_SUFFIX) or parsed.username or parsed.password:
        raise ApiError(
            "not_configured",
            f"{source} must be an https URL on an Autotask host (*{ALLOWED_HOST_SUFFIX}), "
            "e.g. https://webservices5.autotask.net/ATServicesRest/.",
        )
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{host}{port}{REST_PATH}"


def _is_html(response: httpx.Response) -> bool:
    ctype = response.headers.get("content-type", "").lower()
    return "html" in ctype or response.text.lstrip()[:1] == "<"


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        if _is_html(response):
            return "The zone answered with an HTML page (route not available)."
        return response.text.strip()[:300]
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list):
        parts = []
        for err in errors[:5]:
            if isinstance(err, dict):
                err = err.get("message") or err.get("detail") or err
            parts.append(str(err))
        return "; ".join(parts)[:800]
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])[:800]
    return ""


def _has_error_list(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and isinstance(body.get("errors"), list) and bool(body["errors"])


def _status_to_error(status: int, detail: str, business_rule: bool = False) -> ApiError:
    if status == 401:
        return ApiError(
            "unauthorized",
            "Autotask rejected the credentials (401). Check the API user name, secret and integration code.",
            False,
            status,
        )
    if status == 403:
        return ApiError(
            "unauthorized",
            f"The Autotask API user lacks permission for this request (403). {detail}".strip(),
            False,
            status,
        )
    if status == 404:
        return ApiError("not_found", f"Not found in Autotask (404). {detail}".strip(), False, status)
    if status in (400, 405, 409, 415, 422) or (status == 500 and business_rule):
        return ApiError("invalid_argument", f"Autotask refused the request ({status}). {detail}".strip(), False, status)
    if status == 429:
        return ApiError("rate_limited", "Autotask API usage threshold reached (429). Try again shortly.", True, status)
    return ApiError("upstream_error", f"Autotask returned {status}. {detail}".strip(), status >= 500, status)


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return max(0.0, min(float(value), MAX_BACKOFF))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return max(0.0, min(parsed.timestamp() - time.time(), MAX_BACKOFF))
    return min(2.0**attempt, MAX_BACKOFF)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        out[key] = str(value).lower() if isinstance(value, bool) else value
    return out


class AutotaskClient:
    """One instance per tool call; wraps a single httpx client and the zone URL for that call."""

    def __init__(self, creds: Credentials, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._creds = creds
        self._settings = settings
        self._base_url: str | None = None
        self._deadline = time.monotonic() + settings.call_budget_seconds
        self._http = httpx.AsyncClient(
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self) -> "AutotaskClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    # ---- zone -------------------------------------------------------------

    async def base_url(self) -> str:
        if self._base_url is None:
            if self._creds.api_url:
                self._base_url = normalize_base_url(self._creds.api_url, f"The {API_URL_HEADER} header")
            else:
                self._base_url = await self._lookup_zone()
        return self._base_url

    async def _lookup_zone(self) -> str:
        """Find the zone of this API user. Not cached: done once per tool call when no URL header is sent."""
        response = await self._send("GET", ZONE_LOOKUP_URL, params={"user": self._creds.username}, auth=False)
        if response.status_code >= 400:
            raise ApiError(
                "unauthorized",
                f"Autotask zone lookup failed for this API user ({response.status_code}). "
                "Check the API user name (an email address) in the X-Api-Key header.",
                response.status_code >= 500,
                response.status_code,
            )
        try:
            url = (response.json() or {}).get("url")
        except ValueError:
            url = None
        if not url:
            raise ApiError("unauthorized", "Autotask zone lookup returned no zone for this API user.")
        return normalize_base_url(url, "The zone URL returned by Autotask")

    # ---- transport --------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if not self._creds.integration_code:
            raise ApiError(
                "not_configured",
                f"No Autotask API integration code. Send it in the {INTEGRATION_CODE_HEADER} header.",
            )
        return {
            "UserName": self._creds.username,
            "Secret": self._creds.secret,
            "ApiIntegrationCode": self._creds.integration_code,
        }

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        auth: bool = True,
        retry_server_errors: bool = True,
    ) -> httpx.Response:
        headers = self._auth_headers() if auth else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        clean = _clean_params(params)
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, url, params=clean, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                if retry_server_errors and attempt < self._settings.max_retries and self._time_left(1):
                    attempt += 1
                    await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF))
                    continue
                raise ApiError("upstream_error", "Autotask did not respond in time.", True) from exc
            except httpx.HTTPError as exc:
                raise ApiError("upstream_error", f"Could not reach Autotask: {type(exc).__name__}.", True) from exc

            status = response.status_code
            retryable = status == 429 or (
                retry_server_errors and status in RETRY_STATUSES and not _has_error_list(response)
            )
            if retryable and attempt < self._settings.max_retries:
                wait = _retry_after(response, attempt + 1)
                if self._time_left(wait):
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
            return response

    def _time_left(self, needed: float) -> bool:
        return time.monotonic() + needed < self._deadline

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
    ) -> Any:
        """Call ``path`` (relative to the zone REST base) and return the decoded JSON body.

        Creates (POST outside ``/query``) are retried only on 429, so a slow 5xx after the record
        was written cannot create a duplicate.
        """
        method = method.upper()
        self._auth_headers()  # fail fast (before any zone lookup) when the integration code is missing
        is_create = method == "POST" and not path.rstrip("/").lower().endswith(("/query", "/count"))
        url = (await self.base_url()) + path
        response = await self._send(method, url, params=params, body=body, retry_server_errors=not is_create)
        if response.status_code >= 400:
            raise _status_to_error(
                response.status_code, _error_detail(response), business_rule=_has_error_list(response)
            )
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError("upstream_error", "Autotask returned a response that is not JSON.", True) from exc

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any) -> Any:
        return await self.request("POST", path, body=body)

    async def patch(self, path: str, body: Any) -> Any:
        return await self.request("PATCH", path, body=body)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)

    async def first_route(self, method: str, paths: list[str], body: Any = None) -> Any:
        """Try each URL in order, moving on only when the zone answers 404/405 (route not registered).

        Some zones do not register every collection-level route (for example ``POST /Contacts``
        answers with an HTML 404); the parent-scoped child URL works there.
        """
        last: ApiError | None = None
        for path in paths:
            try:
                return await self.request(method, path, body=body)
            except ApiError as exc:
                if exc.status not in (404, 405):
                    raise
                last = exc
        assert last is not None
        raise last

    # ---- entity helpers ---------------------------------------------------

    async def get_item(self, entity: str, item_id: int) -> dict[str, Any]:
        payload = await self.get(f"/{entity}/{item_id}")
        item = (payload or {}).get("item")
        if not item:
            raise ApiError("not_found", f"No {entity} record with id {item_id}.", False, 404)
        return item

    async def query(
        self,
        entity: str,
        filters: list[dict[str, Any]],
        max_records: int = MAX_RECORDS,
        include_fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """One query call (no paging). Autotask needs at least one filter; ``id >= 0`` is used when none."""
        body: dict[str, Any] = {
            "MaxRecords": max(1, min(int(max_records), MAX_RECORDS)),
            "Filter": filters or [{"op": "gte", "field": "id", "value": 0}],
        }
        if include_fields:
            body["IncludeFields"] = include_fields
        payload = await self.request("POST", f"/{entity}/query", body=body)
        items = (payload or {}).get("items") or []
        return [i for i in items if isinstance(i, dict)]

    async def count(self, entity: str, filters: list[dict[str, Any]]) -> int:
        payload = await self.request(
            "POST", f"/{entity}/query/count", body={"Filter": filters or [{"op": "gte", "field": "id", "value": 0}]}
        )
        return int((payload or {}).get("queryCount") or 0)

    async def search(
        self,
        entity: str,
        filters: list[dict[str, Any]],
        page: int,
        page_size: int,
        include_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Page through a query by record id.

        Autotask returns query results in ascending id order and has no offset parameter, so page N
        is read by skipping (N-1)*page_size ids with ``id > cursor`` filters (id-only queries,
        up to 500 per call) and then fetching page_size + 1 records to know whether more exist.
        """
        skip = (page - 1) * page_size
        cursor: int | None = None

        def with_cursor() -> list[dict[str, Any]]:
            if cursor is None:
                return list(filters)
            return [*filters, {"op": "gt", "field": "id", "value": cursor}]

        while skip > 0:
            want = min(skip, MAX_RECORDS)
            batch = await self.query(entity, with_cursor(), want, ["id"])
            ids = sorted(int(i["id"]) for i in batch if isinstance(i.get("id"), int))
            if not ids:
                return page_result([], page, page_size, False)
            cursor = ids[-1]
            skip -= len(ids)
            if len(ids) < want:
                return page_result([], page, page_size, False)

        fields = sorted({*include_fields, "id"}) if include_fields else None
        rows = await self.query(entity, with_cursor(), page_size + 1, fields)
        rows.sort(key=lambda r: r.get("id") if isinstance(r.get("id"), int) else 0)
        return page_result(rows[:page_size], page, page_size, len(rows) > page_size)

    async def picklist(self, entity: str, field: str, active_only: bool = True) -> list[dict[str, Any]]:
        payload = await self.get(f"/{entity}/entityInformation/fields")
        for f in (payload or {}).get("fields") or []:
            if str(f.get("name", "")).lower() == field.lower():
                values = f.get("picklistValues") or []
                return [
                    {"value": v.get("value"), "label": v.get("label"), "isActive": v.get("isActive")}
                    for v in values
                    if not active_only or v.get("isActive", True)
                ]
        raise ApiError("not_found", f"{entity} has no field named {field}.", False, 404)


# ---- result helpers ---------------------------------------------------------


def clean(record: Any, drop: set[str] | None = None) -> Any:
    """Drop null values and empty lists to keep results small."""
    if not isinstance(record, dict):
        return record
    return {k: v for k, v in record.items() if v is not None and v != [] and v != "" and not (drop and k in drop)}


def page_result(rows: list[dict[str, Any]], page: int, page_size: int, has_more: bool, drop=None) -> dict[str, Any]:
    items = [clean(r, drop) for r in rows]
    return {"items": items, "count": len(items), "page_number": page, "page_size": page_size, "has_more": has_more}


def item_id(payload: Any) -> Any:
    if isinstance(payload, dict):
        return payload.get("itemId", payload.get("id"))
    return None


# ---- filter helpers ---------------------------------------------------------


def eq(field: str, value: Any) -> dict[str, Any]:
    return {"op": "eq", "field": field, "value": value}


def op(operator: str, field: str, value: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"op": operator, "field": field}
    if value is not None:
        out["value"] = value
    return out


def any_of(*items: dict[str, Any]) -> dict[str, Any]:
    return {"op": "or", "items": list(items)}


def build(*conditions: tuple[str, str, Any]) -> list[dict[str, Any]]:
    """``build(("eq", "companyID", 5), ("contains", "name", None))`` -> filters for the set values only."""
    return [op(o, f, v) for o, f, v in conditions if v is not None and v != ""]
