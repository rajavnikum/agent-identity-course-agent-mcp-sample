# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Optional
import time
import traceback

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from token_utils import decode_unverified, verify_id_token
from rar_builder import build_agent_authorization_details
from verify_oauth import (
    build_login_url,
    exchange_auth_code,
    get_actor_token,
    token_exchange,
)
from llm_agent import decide_action
from verify_directory import find_verify_user
from mcp_client import list_mcp_tools, call_mcp_tool


app = FastAPI(title="UC2 Conversational Agent with IBM Verify and MCP Tool Gateway")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
templates = Jinja2Templates(directory="templates")


# delete_course_history is deliberately allowed through intent classification and
# Token Exchange as a negative authorization test. The MCP server does NOT expose
# a delete tool, so the request must stop at the MCP tool boundary.
ALLOWED_ACTIONS = {
    "list_available_courses",
    "enroll_course",
    "list_enrolled_courses",
    "delete_course_history",
}


class MCPInvokeRequest(BaseModel):
    tool_name: str
    course_id: str = "ALL"
    requested_subject: str
    logged_in_subject: str
    delegated_token: str


def is_self_reference(value: str | None, logged_in_subject: str) -> bool:
    if not value:
        return True

    value = value.strip().lower()
    return value in {"self", "me", "my", "mine", "myself", logged_in_subject.lower()}


async def resolve_target_subject(
    llm_target_subject: str | None,
    logged_in_subject: str,
) -> tuple[str, dict | None, str]:
    """
    Resolve the target subject without hardcoding users.

    - self/me/my/logged-in username -> logged-in user
    - another name such as John -> IBM Verify Directory lookup

    A named user may exist in the directory and still be denied later by MCP if
    that user is not the currently logged-in subject.
    """
    if is_self_reference(llm_target_subject, logged_in_subject):
        return logged_in_subject, None, "logged_in_subject"

    user_hint = (llm_target_subject or "").strip()
    if not user_hint:
        return logged_in_subject, None, "logged_in_subject"

    resolved_user = await find_verify_user(user_hint)

    if not resolved_user:
        raise ValueError(
            f"No unique IBM Verify user found for hint: {user_hint}. "
            "Use an existing IBM Verify userName, email, or unambiguous name."
        )

    resolved_subject = (
        resolved_user.get("userName")
        or resolved_user.get("displayName")
        or resolved_user.get("id")
    )
    if not resolved_subject:
        raise ValueError(f"IBM Verify user found but no usable username/id for hint: {user_hint}")

    return resolved_subject, resolved_user, "ibm_verify_directory"


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    subject_tokens = request.session.get("subject_tokens")
    subject_identity = request.session.get("subject_identity") or {}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "logged_in": bool(
                subject_tokens
                and subject_tokens.get("access_token")
                and subject_identity
            ),
            # UI identity is always taken from validated ID-token claims.
            "claims": subject_identity,
            "llm_enabled": settings.use_llm,
            "gemini_model": settings.gemini_model,
            "uc_mode": "UC2 - MCP mediated tool access",
            "mcp_server": settings.mcp_server_name,
        },
    )


@app.get("/login")
async def login(request: Request):
    return RedirectResponse(build_login_url(request))


@app.get("/callback")
async def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    if error:
        return JSONResponse(status_code=400, content={"error": error, "error_description": error_description})

    if not code or not state:
        return JSONResponse(status_code=400, content={"error": "Missing code or state"})

    try:
        tokens = await exchange_auth_code(request, code, state)

        id_token = tokens.get("id_token")
        if not id_token:
            raise ValueError("IBM Verify token response did not contain an id_token")

        expected_nonce = request.session.get("oauth_nonce")
        if not expected_nonce:
            raise ValueError("Missing OIDC nonce in session")

        id_claims = verify_id_token(
            id_token,
            expected_nonce=expected_nonce,
        )

        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("IBM Verify token response did not contain an access_token")

        # Identity and OAuth authority are kept separate:
        #   - ID token claims establish the logged-in human identity.
        #   - Access token is kept unchanged and used only as RFC 8693 subject_token.
        # This works whether the subject access token itself is JWT-formatted or opaque.
        request.session["subject_tokens"] = {
            "access_token": access_token,
        }
        request.session["subject_identity"] = id_claims

        request.session.pop("oauth_state", None)
        request.session.pop("oauth_nonce", None)
        request.session.pop("code_verifier", None)

        return RedirectResponse("/")

    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": "Callback processing failed", "details": str(exc)},
        )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")


def _format_course_list(courses) -> str:
    if not courses:
        return ""
    lines = []
    for course in courses:
        if isinstance(course, dict):
            cid = course.get("id", "")
            title = course.get("title", "")
            status = course.get("status")
            if status:
                lines.append(f"- {cid} - {title} ({status})")
            else:
                lines.append(f"- {cid} - {title}")
        else:
            lines.append(f"- {course}")
    return "\n".join(lines)


def build_answer(last_result: dict) -> str:
    if last_result.get("status") == "SUCCESS":
        mcp_result = last_result.get("mcp_result", {}) or last_result.get("api_result", {})
        action = last_result.get("action")

        if action == "list_available_courses":
            courses = mcp_result.get("available_courses") or mcp_result.get("courses", [])
            if not courses:
                return "No courses are currently available to enroll."
            return "Courses available to enroll:\n" + _format_course_list(courses)

        if action == "enroll_course":
            return mcp_result.get("message", "Enrollment completed successfully through MCP tool.")

        if action == "list_enrolled_courses":
            courses = mcp_result.get("enrolled_courses") or mcp_result.get("courses", [])
            if not courses:
                return "No enrolled courses found."
            return "Enrolled courses:\n" + _format_course_list(courses)

        return "Request completed successfully."

    if last_result.get("status") == "USER_RESOLUTION_FAILED":
        return last_result.get("error") or "IBM Verify user resolution failed."

    return (
        last_result.get("error")
        or last_result.get("mcp_result", {}).get("reason")
        or last_result.get("api_result", {}).get("reason")
        or "Request denied or failed."
    )


@app.get("/mcp/tools")
async def mcp_tools():
    return await list_mcp_tools()


@app.post("/mcp/invoke")
async def mcp_invoke(payload: MCPInvokeRequest):
    result = await call_mcp_tool(
        delegated_token=payload.delegated_token,
        tool_name=payload.tool_name,
        course_id=payload.course_id,
        requested_subject=payload.requested_subject,
        logged_in_subject=payload.logged_in_subject,
    )
    return JSONResponse(result, status_code=result.get("http_status", 200))


@app.post("/chat")
async def chat(request: Request, message: str = Form(...)):
    subject_tokens = request.session.get("subject_tokens")
    id_claims = request.session.get("subject_identity") or {}

    # No login means no intent processing, no directory lookup, no actor token,
    # and no Token Exchange. In particular, "show John's courses" cannot reveal
    # whether John exists unless the caller first authenticates.
    if (
        not subject_tokens
        or not subject_tokens.get("access_token")
        or not id_claims
    ):
        return JSONResponse(
            status_code=401,
            content={"error": "Not logged in. Please login with IBM Verify first."},
        )

    # The access token is NOT decoded to discover who logged in. It may be JWT or
    # opaque. It is used only as the subject_token during Token Exchange.
    subject_token = subject_tokens["access_token"]

    if id_claims.get("exp") and int(id_claims["exp"]) < int(time.time()):
        request.session.clear()
        return JSONResponse(
            status_code=401,
            content={"error": "Login session expired. Please login again with IBM Verify."},
        )

    logged_in_subject = (
        id_claims.get("preferred_username")
        or id_claims.get("email")
        or id_claims.get("sub")
        or "unknown-user"
    )

    try:
        decision = decide_action(message)
    except Exception as exc:
        traceback.print_exc()
        last_result = {
            "status": "INTENT_CLASSIFICATION_FAILED",
            "user_message": message,
            "logged_in_subject": logged_in_subject,
            "error": f"Intent classification failed: {str(exc)}",
        }
        return JSONResponse({"answer": build_answer(last_result), "diagnostic": last_result})

    action = decision.action
    course_id = decision.course_id or "ALL"
    llm_target_subject = decision.target_subject or "self"

    if action not in ALLOWED_ACTIONS:
        last_result = {
            "status": "INTENT_CLASSIFICATION_FAILED",
            "user_message": message,
            "logged_in_subject": logged_in_subject,
            "action": action,
            "error": f"Unsupported action from intent classifier: {action}",
        }
        return JSONResponse({"answer": build_answer(last_result), "diagnostic": last_result})

    intent = {
        "action": action,
        "course_id": course_id,
        "llm_target_subject": llm_target_subject,
        "reason": decision.reason,
    }

    # Named users are resolved only after login. If John does not exist (or the
    # lookup is ambiguous), the flow stops here before Token Exchange. If John does
    # exist but another person is logged in, the later MCP cross-user policy denies
    # access to John's course data.
    try:
        target_subject, resolved_verify_user, target_resolution_source = await resolve_target_subject(
            llm_target_subject=llm_target_subject,
            logged_in_subject=logged_in_subject,
        )
    except Exception as exc:
        traceback.print_exc()
        last_result = {
            "status": "USER_RESOLUTION_FAILED",
            "user_message": message,
            "llm_intent": intent,
            "logged_in_subject": logged_in_subject,
            "user_resolution_performed": True,
            "token_exchange_performed": False,
            "mcp_called": False,
            "error": f"IBM Verify user resolution failed for '{llm_target_subject}': {str(exc)}",
        }
        return JSONResponse({"answer": build_answer(last_result), "diagnostic": last_result})

    intent.update(
        {
            "target_subject": target_subject,
            "target_resolution_source": target_resolution_source,
            "resolved_verify_user": resolved_verify_user,
        }
    )

    authorization_details = [
        build_agent_authorization_details(
            creator=settings.actor_client_id or "course-assistant-agent",
            affected_person=target_subject,
            action=action,
            target_system=settings.mcp_server_name,
            resource="mcp-tool",
            course_id=course_id,
            logged_in_subject=logged_in_subject,
            tool_name=action,
            downstream_system=settings.downstream_system,
        )
    ]

    actor_token = None
    delegated_token = None

    try:
        actor_tokens = await get_actor_token()
        actor_token = actor_tokens["access_token"]

        exchanged_tokens = await token_exchange(
            subject_token=subject_token,
            actor_token=actor_token,
            authorization_details=authorization_details,
        )

        delegated_token = exchanged_tokens["access_token"]

        # delete_course_history intentionally reaches this point so the delegated
        # token can demonstrate the STS-derived minimum scope. The MCP client then
        # denies it because the MCP server does not expose a delete tool.
        mcp_result = await call_mcp_tool(
            delegated_token=delegated_token,
            tool_name=action,
            course_id=course_id,
            requested_subject=target_subject,
            logged_in_subject=logged_in_subject,
        )

        last_result = {
            "status": "SUCCESS" if mcp_result.get("allowed") else "DENIED_BY_MCP",
            "user_message": message,
            "llm_enabled": settings.use_llm,
            "llm_model": settings.gemini_model if settings.use_llm else "deterministic-fallback",
            "llm_intent": intent,
            "logged_in_subject": logged_in_subject,
            "requested_subject": target_subject,
            "action": action,
            "mcp_server": settings.mcp_server_name,
            "mcp_tool": action,
            "authorization_details": authorization_details,
            "id_token_claims": id_claims,
            "actor_token_claims": decode_unverified(actor_token),
            "delegated_token_claims": decode_unverified(delegated_token),
            "mcp_result": mcp_result,
        }

    except Exception as exc:
        traceback.print_exc()
        last_result = {
            "status": "DENIED_OR_FAILED",
            "user_message": message,
            "llm_enabled": settings.use_llm,
            "llm_model": settings.gemini_model if settings.use_llm else "deterministic-fallback",
            "llm_intent": intent,
            "logged_in_subject": logged_in_subject,
            "requested_subject": target_subject,
            "action": action,
            "mcp_server": settings.mcp_server_name,
            "mcp_tool": action,
            "authorization_details": authorization_details,
            "id_token_claims": id_claims,
            "actor_token_claims": decode_unverified(actor_token) if actor_token else None,
            "delegated_token_claims": decode_unverified(delegated_token) if delegated_token else None,
            "error": str(exc),
        }

    return JSONResponse({"answer": build_answer(last_result), "diagnostic": last_result})


@app.get("/health")
async def health():
    return {"status": "ok", "uc": "UC2", "mcp_server": settings.mcp_server_name}
