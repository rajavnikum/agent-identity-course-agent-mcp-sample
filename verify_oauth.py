# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import Request

from config import settings


AUTHORIZE_ENDPOINT = settings.authorization_endpoint or f"{settings.verify_issuer}/authorize"
TOKEN_ENDPOINT = settings.token_endpoint or f"{settings.verify_issuer}/token"


def create_pkce_pair():
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("utf-8")).digest()
    ).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def build_login_url(request: Request) -> str:
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    code_verifier, code_challenge = create_pkce_pair()

    request.session["oauth_state"] = state
    request.session["oauth_nonce"] = nonce
    request.session["code_verifier"] = code_verifier

    params = {
        "client_id": settings.subject_client_id,
        "response_type": "code",
        "scope": settings.subject_scopes,
        "redirect_uri": settings.subject_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    return f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"


async def exchange_auth_code(request: Request, code: str, state: str) -> dict:
    expected_state = request.session.get("oauth_state")
    if not expected_state or expected_state != state:
        raise ValueError("Invalid OAuth state")

    code_verifier = request.session.get("code_verifier")
    if not code_verifier:
        raise ValueError("Missing PKCE code_verifier in session")

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.subject_redirect_uri,
        "client_id": settings.subject_client_id,
        "client_secret": settings.subject_client_secret,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Subject token exchange failed: {response.status_code} {response.text}"
        )

    # Do not store the complete token response in the cookie-backed session here.
    # app.py validates the id_token and stores only the access token + ID-token claims.
    return response.json()


async def get_actor_token() -> dict:
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.actor_client_id,
        "client_secret": settings.actor_client_secret,
        "scope": settings.actor_scopes,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Actor token failed: {response.status_code} {response.text}"
        )

    return response.json()


async def token_exchange(
    subject_token: str,
    actor_token: str,
    authorization_details: list,
) -> dict:
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": settings.sts_client_id,
        "client_secret": settings.sts_client_secret,
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": actor_token,
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "authorization_details": json.dumps(authorization_details),
    }

    # Intentionally do NOT send a hard-coded broad scope request here.
    # IBM Verify derives the delegated scope from the granted authorization detail
    # using the STS authorization-details mapping rule documented in README.md.

    audiences = settings.sts_audiences
    if len(audiences) == 1:
        data["audience"] = audiences[0]

    print("\n===== TOKEN EXCHANGE REQUEST =====")
    safe_data = dict(data)
    safe_data["client_secret"] = "***"
    safe_data["subject_token"] = subject_token[:80] + "..."
    safe_data["actor_token"] = actor_token[:80] + "..."
    if len(audiences) > 1:
        safe_data["audience"] = audiences
    print(json.dumps(safe_data, indent=2))
    print("=================================\n")

    if len(audiences) > 1:
        form_data = list(data.items())
        form_data.extend(("audience", aud) for aud in audiences)
    else:
        form_data = data

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            TOKEN_ENDPOINT,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    print("\n===== TOKEN EXCHANGE RESPONSE =====")
    print("STATUS:", response.status_code)
    print("BODY:", response.text)
    print("==================================\n")

    if response.status_code >= 400:
        raise RuntimeError(
            f"STS token exchange failed: {response.status_code} {response.text}"
        )

    return response.json()
