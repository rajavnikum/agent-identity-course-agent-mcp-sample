# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient
from config import settings


def decode_unverified(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})
    except Exception:
        return {}


def verify_id_token(token: str, expected_nonce: str) -> Dict[str, Any]:
    """Validate the OIDC ID token and use it as the logged-in human identity.

    The OAuth access token is deliberately NOT decoded here. It may be JWT-formatted
    or opaque; either form is kept unchanged and is later supplied to IBM Verify as
    the RFC 8693 subject_token with subject_token_type=access_token.
    """
    if not token:
        raise ValueError("Missing OIDC id_token")
    if not expected_nonce:
        raise ValueError("Missing expected OIDC nonce")
    if not settings.jwks_uri:
        raise ValueError("VERIFY_JWKS_URI is required to validate the OIDC id_token")
    if not settings.subject_client_id:
        raise ValueError("SUBJECT_CLIENT_ID is required to validate the OIDC id_token")

    jwk_client = PyJWKClient(settings.jwks_uri)
    signing_key = jwk_client.get_signing_key_from_jwt(token)

    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512"],
        audience=settings.subject_client_id,
        issuer=settings.verify_issuer,
    )

    actual_nonce = claims.get("nonce")
    if actual_nonce != expected_nonce:
        raise ValueError("OIDC nonce mismatch in id_token")

    return claims


async def verify_access_token(token: str, required_scope: Optional[str] = None) -> Dict[str, Any]:
    """Validate a JWT access token locally where a JWT access token is required.

    This helper is for delegated/resource tokens. It is not used to establish the
    browser user's identity; that identity comes from verify_id_token().
    """
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
