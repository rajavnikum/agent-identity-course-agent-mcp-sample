# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Dict, Any, List

from config import settings
from token_utils import decode_unverified


AVAILABLE_COURSES = [
    {"id": "SEC-301", "title": "Advanced Security Operations", "category": "security"},
    {"id": "GEN-101", "title": "AI Productivity Basics", "category": "general"},
    {"id": "GOV-301", "title": "Identity Governance for Managers", "category": "governance"},
]

# Demo in-memory enrollments. Keys are normalized usernames.
# In production this would be a course DB/service.
ENROLLED_COURSES = {
    "scott": [
        {"id": "VERIFY-101", "title": "Demo Course: IBM Verify Agent Identity", "status": "enrolled"},
    ],
    "jessica": [
        {"id": "VERIFY-101", "title": "IBM Verify Fundamentals", "status": "enrolled"},
        {"id": "CLD-201", "title": "Cloud Security Foundations", "status": "enrolled"},
        {"id": "OAUTH-201", "title": "OAuth and Token Exchange Basics", "status": "enrolled"},
    ],
    "john": [
        {"id": "PY-101", "title": "Python Basics", "status": "enrolled"},
        {"id": "DOCKER-101", "title": "Docker Essentials", "status": "enrolled"},
    ],
}

ACTION_SCOPE_MAP = {
    "list_available_courses": "course.read",
    "list_enrolled_courses": "course.read",
    "enroll_course": "course.enroll",
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


def _validate_audience(claims: Dict[str, Any]) -> Dict[str, Any]:
    aud = claims.get("aud")
    audiences = _as_list(aud)
    expected = settings.course_api_audience

    if expected not in audiences:
        return {"valid": False, "reason": f"Invalid audience. Expected '{expected}', token aud={aud}"}

    return {"valid": True}


def _validate_actor(claims: Dict[str, Any]) -> Dict[str, Any]:
    act = claims.get("act")

    if not act:
        return {"valid": False, "reason": "Missing actor claim 'act' in delegated token"}

    expected_actor = settings.actor_client_id
    actor_sub = None

    if isinstance(act, dict):
        actor_sub = act.get("sub") or act.get("client_id")

    if expected_actor and actor_sub and actor_sub != expected_actor:
        return {"valid": False, "reason": f"Invalid actor. Expected '{expected_actor}', token act.sub={actor_sub}"}

    return {"valid": True}


def _validate_authorization_details(
    claims: Dict[str, Any],
    action: str,
    requested_subject: str,
    logged_in_subject: str,
) -> Dict[str, Any]:
    auth_details = claims.get("authorization_details") or claims.get("authorization_details_types") or []

    if not auth_details:
        return {"valid": False, "reason": "Missing authorization_details in delegated token"}

    if isinstance(auth_details, dict):
        auth_details = [auth_details]

    matched = None
    for item in auth_details:
        if item.get("type") == settings.agent_adt_type:
            matched = item
            break

    if not matched:
        return {"valid": False, "reason": f"Missing expected ADT type: {settings.agent_adt_type}"}

    operation = matched.get("operationDetails", {})
    rar_action = operation.get("action")
    affected_person = operation.get("affectedPerson")
    logged_in_from_rar = operation.get("loggedInSubject")

    if rar_action != action:
        return {"valid": False, "reason": f"RAR action mismatch. API action={action}, RAR action={rar_action}"}

    if _normalize_subject(affected_person) != _normalize_subject(requested_subject):
        return {"valid": False, "reason": "RAR affectedPerson does not match requested subject"}

    if logged_in_from_rar and _normalize_subject(logged_in_from_rar) != _normalize_subject(logged_in_subject):
        return {"valid": False, "reason": "RAR loggedInSubject does not match logged-in subject"}

    return {"valid": True, "authorization_detail": matched}


def _validate_scope(claims: Dict[str, Any], action: str) -> Dict[str, Any]:
    required_scope = ACTION_SCOPE_MAP.get(action)

    if not required_scope:
        return {"valid": False, "reason": f"Unsupported action: {action}"}

    scopes = _scope_list(claims)

    if required_scope not in scopes:
        return {"valid": False, "reason": f"Missing required scope: {required_scope}. Token scopes={scopes}"}

    return {"valid": True}


def _deny(reason: str, claims: Dict[str, Any], http_status: int = 403) -> Dict[str, Any]:
    return {"allowed": False, "reason": reason, "http_status": http_status, "claims_seen_by_api": claims}


def _validation_passed(claims: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "claims_seen_by_api": claims,
        "validation": {
            "scope": "passed",
            "audience": "passed",
            "actor": "passed",
            "authorization_details": "passed",
        },
    }


def _course_title(course: Dict[str, Any]) -> str:
    return f"{course.get('id')} - {course.get('title')}"


def _find_available_course(course_id: str) -> Dict[str, Any] | None:
    for course in AVAILABLE_COURSES:
        if course.get("id") == course_id:
            return course
    return None


def call_course_api(
    delegated_token: str,
    action: str,
    requested_subject: str,
    logged_in_subject: str,
) -> Dict[str, Any]:
    claims = decode_unverified(delegated_token)

    requested = _normalize_subject(requested_subject)
    logged_in = _normalize_subject(logged_in_subject)

    # Course API policy: this demo only permits self-service access.
    # If scott asks for rick's enrolled courses, the delegated token may be issued,
    # but the API denies because requested subject != logged-in subject.
    if requested != logged_in:
        return _deny("Requested subject does not match logged-in subject", claims)

    scope_check = _validate_scope(claims, action)
    if not scope_check["valid"]:
        return _deny(scope_check["reason"], claims)

    audience_check = _validate_audience(claims)
    if not audience_check["valid"]:
        return _deny(audience_check["reason"], claims)

    actor_check = _validate_actor(claims)
    if not actor_check["valid"]:
        return _deny(actor_check["reason"], claims)

    ad_check = _validate_authorization_details(
        claims=claims,
        action=action,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )
    if not ad_check["valid"]:
        return _deny(ad_check["reason"], claims)

    base = _validation_passed(claims)

    if action == "list_available_courses":
        return {
            "allowed": True,
            "http_status": 200,
            "operation": "list_available_courses",
            "available_courses": AVAILABLE_COURSES,
            "courses": [_course_title(c) for c in AVAILABLE_COURSES],
            **base,
        }

    if action == "list_enrolled_courses":
        enrolled = ENROLLED_COURSES.get(logged_in, [])
        return {
            "allowed": True,
            "http_status": 200,
            "operation": "list_enrolled_courses",
            "enrolled_courses": enrolled,
            "courses": [_course_title(c) for c in enrolled],
            **base,
        }

    if action == "enroll_course":
        auth_details = claims.get("authorization_details") or []
        if isinstance(auth_details, dict):
            auth_details = [auth_details]

        course_id = "UNKNOWN"
        for item in auth_details:
            if item.get("type") == settings.agent_adt_type:
                course_id = item.get("courseId") or "UNKNOWN"
                break

        if course_id == "UNKNOWN":
            return _deny("Course ID is required for enrollment", claims, http_status=400)

        course = _find_available_course(course_id)
        if not course:
            return _deny(f"Course not found or not available to enroll: {course_id}", claims, http_status=404)

        enrolled = ENROLLED_COURSES.setdefault(logged_in, [])
        if not any(c.get("id") == course_id for c in enrolled):
            enrolled.append({"id": course["id"], "title": course["title"], "status": "enrolled"})
            message = f"User enrolled successfully in {course['id']} - {course['title']}"
        else:
            message = f"User is already enrolled in {course['id']} - {course['title']}"

        return {
            "allowed": True,
            "http_status": 200,
            "operation": "enroll_course",
            "message": message,
            "enrolled_courses": enrolled,
            **base,
        }

    return _deny(f"Unsupported action: {action}", claims, http_status=400)
