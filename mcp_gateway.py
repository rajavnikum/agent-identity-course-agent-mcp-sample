# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Dict, List
import json
import time

from config import settings
from token_utils import decode_unverified
from course_api import (
    AVAILABLE_COURSES,
    ENROLLED_COURSES,
    call_course_api,
)


TOOL_DEFINITIONS = [
    {
        "name": "list_available_courses",
        "description": "List courses that are available to enroll.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "enroll_course",
        "description": "Enroll the authenticated subject into a course.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string"}
            },
            "required": ["course_id"],
        },
    },
    {
        "name": "list_enrolled_courses",
        "description": "List courses already enrolled or taken by the requested subject.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


ACTION_SCOPE_MAP = {
    "list_available_courses": {"mcp.tools.invoke", "course.read"},
    "list_enrolled_courses": {"mcp.tools.invoke", "course.read"},
    "enroll_course": {"mcp.tools.invoke", "course.enroll"},
}

# delete_course_history is intentionally NOT exposed as an MCP tool.
# Its ADT mapping grants only mcp.tools.invoke, and mcp_client.py denies the
# invocation because tools/list does not contain a delete tool.


def _mcp_log(title: str, data: Dict[str, Any] | None = None) -> None:
    print("\n" + "=" * 20 + f" MCP: {title} " + "=" * 20)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"MCP Server Name: {settings.mcp_server_name}")
    print(f"MCP Audience: {settings.mcp_audience}")
    print(f"Downstream System: {settings.downstream_system}")
    print(f"Forward To Course API: {settings.mcp_forward_to_course_api}")

    if data:
        print(json.dumps(data, indent=2, default=str))

    print("=" * 60 + "\n")


def list_mcp_tools() -> Dict[str, Any]:
    _mcp_log(
        "TOOL DISCOVERY",
        {
            "endpoint": "/mcp/tools",
            "tools_available": [tool["name"] for tool in TOOL_DEFINITIONS],
        },
    )

    return {
        "server": settings.mcp_server_name,
        "port": 8000,
        "transport": "in-process FastAPI demo endpoint",
        "tools": TOOL_DEFINITIONS,
        "note": (
            "For UC2 demo simplicity, the MCP gateway runs inside the same "
            "FastAPI process as the chat app. In production it can be a separate service."
        ),
    }


def _normalize_subject(subject: str) -> str:
    if not subject:
        return "unknown-user"
    return subject.split("@")[0].lower()


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _scope_list(claims: Dict[str, Any]) -> List[str]:
    scope = claims.get("scope") or claims.get("scp") or ""
    if isinstance(scope, list):
        return scope
    return str(scope).split()


def _deny(
    reason: str,
    claims: Dict[str, Any] | None = None,
    http_status: int = 403,
    stage: str = "mcp_policy",
) -> Dict[str, Any]:
    _mcp_log(
        "DENIED",
        {
            "stage": stage,
            "reason": reason,
            "http_status": http_status,
        },
    )

    return {
        "allowed": False,
        "reason": reason,
        "http_status": http_status,
        "denied_by": "mcp_gateway",
        "denied_stage": stage,
        "claims_seen_by_mcp": claims or {},
    }


def _find_auth_detail(claims: Dict[str, Any]) -> Dict[str, Any] | None:
    auth_details = claims.get("authorization_details") or []

    if isinstance(auth_details, dict):
        auth_details = [auth_details]

    for item in auth_details:
        if item.get("type") == settings.agent_adt_type:
            return item

    return None


def _validate_mcp_invocation(
    claims: Dict[str, Any],
    tool_name: str,
    requested_subject: str,
    logged_in_subject: str,
) -> Dict[str, Any]:
    _mcp_log(
        "VALIDATION START",
        {
            "tool_requested": tool_name,
            "requested_subject": requested_subject,
            "logged_in_subject": logged_in_subject,
            "token_audience": claims.get("aud"),
            "token_scope": claims.get("scope"),
            "token_subject": claims.get("preferred_username") or claims.get("sub"),
            "token_actor": claims.get("act"),
            "adt_type_expected": settings.agent_adt_type,
        },
    )

    audiences = _as_list(claims.get("aud"))

    if settings.mcp_audience not in audiences:
        return {
            "valid": False,
            "stage": "audience",
            "reason": (
                f"Invalid MCP audience. Expected '{settings.mcp_audience}', "
                f"token aud={claims.get('aud')}"
            ),
        }

    act = claims.get("act")

    if not act:
        return {
            "valid": False,
            "stage": "actor",
            "reason": "Missing actor claim 'act' in delegated token",
        }

    actor_sub = None

    if isinstance(act, dict):
        actor_sub = act.get("sub") or act.get("client_id")

    if settings.actor_client_id and actor_sub and actor_sub != settings.actor_client_id:
        return {
            "valid": False,
            "stage": "actor",
            "reason": (
                f"Invalid actor. Expected '{settings.actor_client_id}', "
                f"token act.sub={actor_sub}"
            ),
        }

    required_scopes = ACTION_SCOPE_MAP.get(tool_name)

    if not required_scopes:
        return {
            "valid": False,
            "stage": "tool",
            "reason": f"Unsupported MCP tool: {tool_name}",
        }

    scopes = set(_scope_list(claims))
    missing_scopes = sorted(required_scopes - scopes)

    if missing_scopes:
        return {
            "valid": False,
            "stage": "scope",
            "reason": (
                f"Missing required scope(s) for {tool_name}: {missing_scopes}. "
                f"Token scopes={sorted(scopes)}"
            ),
        }

    auth_detail = _find_auth_detail(claims)

    if not auth_detail:
        return {
            "valid": False,
            "stage": "authorization_details",
            "reason": f"Missing expected ADT type: {settings.agent_adt_type}",
        }

    operation = auth_detail.get("operationDetails") or {}

    rar_action = operation.get("action")
    rar_tool = operation.get("toolName")
    target_system = operation.get("targetSystem")
    downstream_system = operation.get("downstreamSystem")
    affected_person = operation.get("affectedPerson")
    logged_in_from_rar = operation.get("loggedInSubject")
    resource = operation.get("resource")

    _mcp_log(
        "RAR RECEIVED",
        {
            "authorization_detail": auth_detail,
            "rar_action": rar_action,
            "rar_tool": rar_tool,
            "target_system": target_system,
            "resource": resource,
            "downstream_system": downstream_system,
            "affected_person": affected_person,
            "logged_in_from_rar": logged_in_from_rar,
        },
    )

    if target_system != settings.mcp_server_name:
        return {
            "valid": False,
            "stage": "target_system",
            "reason": f"RAR targetSystem must be {settings.mcp_server_name}, got {target_system}",
        }

    if resource != "mcp-tool":
        return {
            "valid": False,
            "stage": "resource",
            "reason": f"RAR resource must be mcp-tool, got {resource}",
        }

    if downstream_system and downstream_system != settings.downstream_system:
        return {
            "valid": False,
            "stage": "downstream_system",
            "reason": (
                f"RAR downstreamSystem must be {settings.downstream_system}, "
                f"got {downstream_system}"
            ),
        }

    if rar_action != tool_name:
        return {
            "valid": False,
            "stage": "action",
            "reason": f"RAR action mismatch. MCP tool={tool_name}, RAR action={rar_action}",
        }

    if rar_tool != tool_name:
        return {
            "valid": False,
            "stage": "tool_name",
            "reason": f"RAR toolName mismatch. MCP tool={tool_name}, RAR toolName={rar_tool}",
        }

    if _normalize_subject(affected_person) != _normalize_subject(requested_subject):
        return {
            "valid": False,
            "stage": "affected_person",
            "reason": "RAR affectedPerson does not match requested subject",
        }

    if logged_in_from_rar and _normalize_subject(logged_in_from_rar) != _normalize_subject(logged_in_subject):
        return {
            "valid": False,
            "stage": "logged_in_subject",
            "reason": "RAR loggedInSubject does not match logged-in subject",
        }

    if _normalize_subject(requested_subject) != _normalize_subject(logged_in_subject):
        return {
            "valid": False,
            "stage": "cross_user_policy",
            "reason": "MCP policy denied: requested subject does not match logged-in subject",
        }

    _mcp_log(
        "VALIDATION PASSED",
        {
            "tool": tool_name,
            "audience": "passed",
            "actor": "passed",
            "scope": "passed",
            "authorization_details": "passed",
            "subject_policy": "passed",
        },
    )

    return {
        "valid": True,
        "authorization_detail": auth_detail,
    }


def _course_title(course: Dict[str, Any]) -> str:
    return f"{course.get('id')} - {course.get('title')}"


def _find_available_course(course_id: str) -> Dict[str, Any] | None:
    for course in AVAILABLE_COURSES:
        if course.get("id") == course_id:
            return course

    return None


def _execute_tool_locally(
    tool_name: str,
    course_id: str,
    logged_in_subject: str,
    claims: Dict[str, Any],
) -> Dict[str, Any]:
    logged_in = _normalize_subject(logged_in_subject)

    validation = {
        "scope": "passed",
        "audience": "passed",
        "actor": "passed",
        "authorization_details": "passed",
        "mcp_tool_policy": "passed",
    }

    _mcp_log(
        "LOCAL TOOL EXECUTION START",
        {
            "tool": tool_name,
            "course_id": course_id,
            "logged_in_subject": logged_in_subject,
            "normalized_subject": logged_in,
        },
    )

    if tool_name == "list_available_courses":
        result = {
            "allowed": True,
            "http_status": 200,
            "operation": "list_available_courses",
            "mcp_tool": tool_name,
            "executed_by": "mcp_gateway",
            "execution_mode": "local_mcp_tool",
            "available_courses": AVAILABLE_COURSES,
            "courses": [_course_title(c) for c in AVAILABLE_COURSES],
            "claims_seen_by_mcp": claims,
            "validation": validation,
        }

        _mcp_log(
            "LOCAL TOOL EXECUTION COMPLETE",
            {
                "tool": tool_name,
                "course_count": len(AVAILABLE_COURSES),
            },
        )

        return result

    if tool_name == "list_enrolled_courses":
        enrolled = ENROLLED_COURSES.get(logged_in, [])

        result = {
            "allowed": True,
            "http_status": 200,
            "operation": "list_enrolled_courses",
            "mcp_tool": tool_name,
            "executed_by": "mcp_gateway",
            "execution_mode": "local_mcp_tool",
            "enrolled_courses": enrolled,
            "courses": [_course_title(c) for c in enrolled],
            "claims_seen_by_mcp": claims,
            "validation": validation,
        }

        _mcp_log(
            "LOCAL TOOL EXECUTION COMPLETE",
            {
                "tool": tool_name,
                "enrolled_course_count": len(enrolled),
            },
        )

        return result

    if tool_name == "enroll_course":
        if not course_id or course_id == "UNKNOWN" or course_id == "ALL":
            return _deny(
                "Course ID is required for enrollment",
                claims,
                http_status=400,
                stage="tool_input_validation",
            )

        course = _find_available_course(course_id)

        if not course:
            return _deny(
                f"Course not found or not available to enroll: {course_id}",
                claims,
                http_status=404,
                stage="tool_input_validation",
            )

        enrolled = ENROLLED_COURSES.setdefault(logged_in, [])

        if not any(c.get("id") == course_id for c in enrolled):
            enrolled.append(
                {
                    "id": course["id"],
                    "title": course["title"],
                    "status": "enrolled",
                }
            )
            message = f"MCP tool enrolled user successfully in {course['id']} - {course['title']}"
        else:
            message = f"User is already enrolled in {course['id']} - {course['title']}"

        result = {
            "allowed": True,
            "http_status": 200,
            "operation": "enroll_course",
            "mcp_tool": tool_name,
            "executed_by": "mcp_gateway",
            "execution_mode": "local_mcp_tool",
            "message": message,
            "enrolled_courses": enrolled,
            "claims_seen_by_mcp": claims,
            "validation": validation,
        }

        _mcp_log(
            "LOCAL TOOL EXECUTION COMPLETE",
            {
                "tool": tool_name,
                "course_id": course_id,
                "message": message,
            },
        )

        return result

    return _deny(
        f"Unsupported MCP tool: {tool_name}",
        claims,
        http_status=400,
        stage="tool_dispatch",
    )


def invoke_mcp_tool(
    delegated_token: str,
    tool_name: str,
    course_id: str,
    requested_subject: str,
    logged_in_subject: str,
) -> Dict[str, Any]:
    """
    UC2 MCP-style tool invocation.

    Demo mode:
      - Chat app and MCP gateway run in the same FastAPI process on port 8000.
      - MCP validates the IBM Verify delegated token.
      - MCP validates audience, actor, scope and authorization_details.
      - MCP executes the mock course tool locally.

    Defense-in-depth mode:
      - If MCP_FORWARD_TO_COURSE_API=true, MCP validates first.
      - Then MCP forwards the same delegated token to the downstream Course API validation layer.
      - This requires the delegated token audience to include both course-mcp-server and course-api.
    """

    _mcp_log(
        "INVOCATION RECEIVED",
        {
            "transport": "in-process call from /chat OR HTTP /mcp/invoke",
            "port": 8000,
            "tool_name": tool_name,
            "course_id": course_id,
            "requested_subject": requested_subject,
            "logged_in_subject": logged_in_subject,
        },
    )

    claims = decode_unverified(delegated_token)

    check = _validate_mcp_invocation(
        claims=claims,
        tool_name=tool_name,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )

    if not check["valid"]:
        return _deny(
            check["reason"],
            claims,
            stage=check.get("stage", "mcp_validation"),
        )

    if settings.mcp_forward_to_course_api:
        _mcp_log(
            "FORWARDING TO DOWNSTREAM COURSE API",
            {
                "tool": tool_name,
                "course_id": course_id,
                "downstream_system": settings.downstream_system,
                "note": "The same delegated token is forwarded after MCP validation.",
            },
        )

        downstream_result = call_course_api(
            delegated_token=delegated_token,
            action=tool_name,
            requested_subject=requested_subject,
            logged_in_subject=logged_in_subject,
        )

        downstream_result["executed_by"] = "mcp_gateway_then_course_api"
        downstream_result["execution_mode"] = "forwarded_to_downstream_api"
        downstream_result["mcp_validation"] = {
            "mcp_audience": "passed",
            "mcp_actor": "passed",
            "mcp_scope": "passed",
            "mcp_authorization_details": "passed",
            "forwarded_to_downstream_api": True,
        }

        _mcp_log(
            "DOWNSTREAM COURSE API RESULT",
            {
                "allowed": downstream_result.get("allowed"),
                "http_status": downstream_result.get("http_status"),
                "operation": downstream_result.get("operation"),
                "reason": downstream_result.get("reason"),
            },
        )

        return downstream_result

    return _execute_tool_locally(
        tool_name=tool_name,
        course_id=course_id,
        logged_in_subject=logged_in_subject,
        claims=claims,
    )