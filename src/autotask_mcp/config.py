# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Process-level settings. Tenant credentials are never read from here."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Request headers (matched case-insensitively).
API_KEY_HEADER = "X-Api-Key"  # Autotask API user name (UserName)
API_SECRET_HEADER = "X-Api-Secret"  # Autotask API user secret (Secret)
INTEGRATION_CODE_HEADER = "X-Integration-Code"  # Autotask API tracking identifier (ApiIntegrationCode)
API_URL_HEADER = "X-Api-Url"  # Zone REST base URL; looked up per request when absent

REQUIRED_HEADERS = [API_KEY_HEADER, API_SECRET_HEADER]
OPTIONAL_HEADERS = [INTEGRATION_CODE_HEADER, API_URL_HEADER]

# Official zone lookup endpoint (no authentication needed).
ZONE_LOOKUP_URL = "https://webservices.autotask.net/ATServicesRest/v1.0/zoneInformation"

# Every Autotask zone lives under this domain. A zone URL from a header or from the
# zone lookup must be HTTPS on this domain, so credentials are never sent elsewhere.
ALLOWED_HOST_SUFFIX = ".autotask.net"
REST_PATH = "/ATServicesRest/v1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_transport: Literal["stdio", "http"] = "http"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Outbound HTTP behaviour.
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3
    # Upper bound for one tool call including retries (must stay below 120s).
    call_budget_seconds: float = 100.0


def get_settings() -> Settings:
    return Settings()
