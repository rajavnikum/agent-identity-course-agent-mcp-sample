# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _csv_or_space(value: str) -> list[str]:
    if not value:
        return []
    value = value.replace(',', ' ')
    return [v.strip() for v in value.split() if v.strip()]


@dataclass(frozen=True)
class Settings:
    # LLM switch. If false, llm_agent.py uses deterministic fallback parsing.
    use_llm: bool = os.getenv("USE_LLM", "false").lower() == "true"

    # IBM Verify authorization server endpoints
    verify_issuer: str = os.getenv("VERIFY_ISSUER", "").rstrip("/")
    authorization_endpoint: str = os.getenv("VERIFY_AUTHORIZATION_ENDPOINT", "")
    token_endpoint: str = os.getenv("VERIFY_TOKEN_ENDPOINT", "")
    jwks_uri: str = os.getenv("VERIFY_JWKS_URI", "")
    introspection_endpoint: str = os.getenv("VERIFY_INTROSPECTION_ENDPOINT", "")

    # Subject client - human user login by Authorization Code flow
    subject_client_id: str = os.getenv("SUBJECT_CLIENT_ID", "")
    subject_client_secret: str = os.getenv("SUBJECT_CLIENT_SECRET", "")
    subject_redirect_uri: str = os.getenv("SUBJECT_REDIRECT_URI", "http://localhost:8000/callback")
    subject_scopes: str = os.getenv("SUBJECT_SCOPES", "openid profile email course.read course.enroll")

    # Actor client - registered AI agent runtime identity
    actor_client_id: str = os.getenv("ACTOR_CLIENT_ID", "")
    actor_client_secret: str = os.getenv("ACTOR_CLIENT_SECRET", "")
    actor_scopes: str = os.getenv("ACTOR_SCOPES", "agent.run")

    # STS client - OAuth 2.0 Token Exchange client
    sts_client_id: str = os.getenv("STS_CLIENT_ID", "")
    sts_client_secret: str = os.getenv("STS_CLIENT_SECRET", "")
    sts_requested_scope: str = os.getenv("STS_REQUESTED_SCOPE", "mcp.tools.invoke course.read course.enroll")

    # Optional explicit audience parameter sent to STS.
    # For UC2 demo keep this as course-mcp-server. For defense in depth, use both:
    # STS_AUDIENCE=course-mcp-server course-api
    sts_audience: str = os.getenv("STS_AUDIENCE", os.getenv("MCP_AUDIENCE", "course-mcp-server"))

    # Verify Directory / SCIM lookup client.
    # Use a separate API/management client with permission to read users.
    verify_management_client_id: str = os.getenv("VERIFY_MANAGEMENT_CLIENT_ID", "")
    verify_management_client_secret: str = os.getenv("VERIFY_MANAGEMENT_CLIENT_SECRET", "")
    verify_management_scopes: str = os.getenv("VERIFY_MANAGEMENT_SCOPES", "")

    # RAR / ADT
    agent_adt_type: str = os.getenv("AGENT_ADT_TYPE", "urn:ibm:demo:verify:agent_action")

    # UC2 MCP and downstream resource names
    mcp_audience: str = os.getenv("MCP_AUDIENCE", "course-mcp-server")
    mcp_server_name: str = os.getenv("MCP_SERVER_NAME", "course-mcp-server")
    downstream_system: str = os.getenv("DOWNSTREAM_SYSTEM", "course-api")
    course_api_audience: str = os.getenv("COURSE_API_AUDIENCE", "course-api")

    # If true, MCP validates the token then forwards the same delegated token to the
    # downstream Course API validation layer. This requires the delegated token aud to
    # include course-api, usually by setting STS_AUDIENCE="course-mcp-server course-api".
    mcp_forward_to_course_api: bool = os.getenv("MCP_FORWARD_TO_COURSE_API", "false").lower() == "true"

    # Optional Gemini LLM. If missing or USE_LLM=false, deterministic fallback works.
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Local app
    allow_local_unsigned_jwt: bool = os.getenv("ALLOW_LOCAL_UNSIGNED_JWT", "false").lower() == "true"
    session_secret: str = os.getenv("SESSION_SECRET", "change-me-for-demo")
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    @property
    def sts_audiences(self) -> list[str]:
        return _csv_or_space(self.sts_audience)


settings = Settings()
