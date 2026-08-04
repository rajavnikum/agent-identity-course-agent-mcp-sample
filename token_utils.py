# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import jwt
import httpx
from jwt import PyJWKClient
from config import settings


def decode_unverified(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    except Exception:
        return {}


async def verify_access_token(token: str, required_scope: Optional[str] = None) -> Dict[str, Any]:
    """Validate token locally with JWKS if configured. For demos, unsigned local decode can be enabled."""
    if settings.allow_local_unsigned_jwt:
        claims = decode_unverified(token)
    else:
        jwk_client = PyJWKClient(settings.jwks_uri)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=None,
            issuer=settings.verify_issuer,
            options={"verify_aud": False},
        )
    if required_scope:
        scopes = set(str(claims.get("scope", "")).split())
        if required_scope not in scopes:
            raise PermissionError(f"Missing required scope: {required_scope}")
    return claims


def extract_authorization_details(claims: Dict[str, Any]) -> list[Dict[str, Any]]:
    ad = claims.get("authorization_details") or claims.get("authorization_details_json") or []
    if isinstance(ad, str):
        try:
            return json.loads(ad)
        except Exception:
            return []
    if isinstance(ad, list):
        return ad
    return []
