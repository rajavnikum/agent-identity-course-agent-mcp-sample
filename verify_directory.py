# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import httpx

from config import settings


def _tenant_base() -> str:
    issuer = settings.verify_issuer.rstrip("/")
    if issuer.endswith("/oauth2"):
        return issuer[: -len("/oauth2")]
    if "/oauth2/" in issuer:
        return issuer.split("/oauth2/")[0]
    return issuer.replace("/oauth2", "")


def _token_endpoint() -> str:
    if settings.token_endpoint:
        return settings.token_endpoint
    return f"{settings.verify_issuer.rstrip('/')}/token"


def _escape_scim_value(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


async def get_verify_management_token() -> str:
    """
    Gets a Verify API/management token using client_credentials.
    The configured client must be allowed to read users from Verify Directory/SCIM.
    """
    if not settings.verify_management_client_id or not settings.verify_management_client_secret:
        raise RuntimeError(
            "VERIFY_MANAGEMENT_CLIENT_ID and VERIFY_MANAGEMENT_CLIENT_SECRET are required "
            "to resolve non-self users from IBM Verify Directory."
        )

    data = {
        "grant_type": "client_credentials",
        "client_id": settings.verify_management_client_id,
        "client_secret": settings.verify_management_client_secret,
    }

    if settings.verify_management_scopes:
        data["scope"] = settings.verify_management_scopes

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _token_endpoint(),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Verify management token failed: {response.status_code} {response.text}")

    return response.json()["access_token"]


async def find_verify_user(user_hint: str) -> dict | None:
    """
    Resolve a natural user hint to exactly one IBM Verify user.
    Returns None when zero or multiple users match.
    """
    hint = (user_hint or "").strip()
    if not hint:
        return None

    token = await get_verify_management_token()
    safe_hint = _escape_scim_value(hint)

    # Prefix match works for names like "rick" -> "rickmood" if Verify userName/displayName starts with rick.
    # Also checks email prefix/value and given/family name where available.
    filter_value = (
        f'userName sw "{safe_hint}" '
        f'or displayName sw "{safe_hint}" '
        f'or name.givenName sw "{safe_hint}" '
        f'or name.familyName sw "{safe_hint}" '
        f'or emails.value sw "{safe_hint}"'
    )

    url = f"{_tenant_base().rstrip('/')}/v2.0/Users"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/scim+json"},
            params={"filter": filter_value, "count": 2},
        )

    if response.status_code >= 400:
        raise RuntimeError(f"Verify user lookup failed: {response.status_code} {response.text}")

    data = response.json()
    resources = data.get("Resources", [])

    if len(resources) != 1:
        return None

    user = resources[0]
    return {
        "id": user.get("id"),
        "userName": user.get("userName"),
        "displayName": user.get("displayName"),
        "emails": user.get("emails", []),
    }
