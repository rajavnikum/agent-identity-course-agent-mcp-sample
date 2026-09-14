# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from config import settings

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


@dataclass
class AgentDecision:
    action: str
    course_id: str
    reason: str
    target_subject: Optional[str] = "self"


ALLOWED_ACTIONS = {
    "list_available_courses",
    "enroll_course",
    "list_enrolled_courses",
    "delete_course_history",
}

COURSE_MAP = {
    "advanced security training": "SEC-301",
    "advanced security": "SEC-301",
    "security training": "SEC-301",
    "advanced security operations": "SEC-301",
    "ai productivity": "GEN-101",
    "productivity basics": "GEN-101",
    "identity governance": "GOV-301",
    "governance for managers": "GOV-301",
}

SYSTEM_INSTRUCTION = """
You are an intent classifier for a course-booking demo agent.
Return ONLY valid JSON. Do not return markdown.

Allowed action values only:
1. list_available_courses
2. enroll_course
3. list_enrolled_courses
4. delete_course_history

Meaning:
- list_available_courses: user asks what courses are available/catalog/can enroll in.
- enroll_course: user asks to enroll/book/register/join a course.
- list_enrolled_courses: user asks what courses are already taken/enrolled/completed by self or someone else.
- delete_course_history: user asks to delete/remove/erase course history or enrollment history. This is a deliberate negative authorization test; the MCP server does not expose a delete tool.

Target subject rules:
- For "my", "me", "mine", "myself" return target_subject="self".
- If another person is named, return only the name/hint exactly enough for lookup in IBM Verify Directory.
- Do not invent usernames.

Course rules:
- For list_available_courses, list_enrolled_courses, and delete_course_history, course_id="ALL".
- For enroll_course, identify course_id when possible.
- advanced security training / advanced security operations => SEC-301.
- AI productivity basics => GEN-101.
- identity governance for managers => GOV-301.
- If the requested course is unclear for enroll_course, course_id="UNKNOWN".

Examples:
User: What courses are there to enroll?
{"action":"list_available_courses","course_id":"ALL","target_subject":"self","reason":"User asked for catalog courses available to enroll."}

User: Please enroll me into advanced security training
{"action":"enroll_course","course_id":"SEC-301","target_subject":"self","reason":"User asked to enroll self into advanced security training."}

User: Show my enrolled courses
{"action":"list_enrolled_courses","course_id":"ALL","target_subject":"self","reason":"User asked for their enrolled courses."}

User: Can you show John's courses?
{"action":"list_enrolled_courses","course_id":"ALL","target_subject":"John","reason":"User asked for another person's enrolled courses."}

User: Please delete my course history
{"action":"delete_course_history","course_id":"ALL","target_subject":"self","reason":"User requested deletion of course history."}
"""

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        if genai is None:
            raise RuntimeError("google-genai package is not available")
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _extract_course_id(text: str) -> str:
    lowered = text.lower()
    for label, course_id in COURSE_MAP.items():
        if label in lowered:
            return course_id

    m = re.search(r"\b[A-Z]{2,10}-\d{2,5}\b", text.upper())
    if m:
        return m.group(0)

    return "UNKNOWN"


def _extract_target_hint_without_llm(message: str) -> str:
    text = message.strip()
    lowered = text.lower()

    if re.search(r"\b(my|me|mine|myself)\b", lowered):
        return "self"

    m = re.search(r"\b(?:by|for|of)\s+([A-Za-z0-9._@'-]+)", text, re.IGNORECASE)
    if m:
        candidate = m.group(1).strip(" ?.,!\r\n\t'")
        if candidate:
            return candidate

    # Handles both "show John courses" and "show John's courses".
    m = re.search(
        r"\b(?:show|list|display|view)\s+([A-Za-z0-9._@-]+)(?:'s)?\s+(?:course|courses|enrollment|enrollments)\b",
        text,
        re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip(" ?.,!\r\n\t'")
        if candidate.lower() not in {"available", "catalog", "my", "me", "enrolled"}:
            return candidate

    return "self"


def fallback_decide(message: str) -> AgentDecision:
    text = message.lower()
    target_subject = _extract_target_hint_without_llm(message)

    # Delete must be recognized before generic "courses" handling.
    if any(w in text for w in ["delete", "remove", "erase"]) and any(
        w in text for w in ["course", "courses", "history", "enrollment", "enrollments"]
    ):
        return AgentDecision(
            action="delete_course_history",
            course_id="ALL",
            target_subject=target_subject,
            reason="Deterministic fallback: delete-course-history request.",
        )

    if re.search(r"\b(enroll|enrol|register|join|book)\b", text):
        return AgentDecision(
            action="enroll_course",
            course_id=_extract_course_id(message),
            target_subject=target_subject,
            reason="Deterministic fallback: enrollment request.",
        )

    if (
        "available" in text
        or "catalog" in text
        or "to enroll" in text
        or "can i enroll" in text
        or "courses are there" in text
    ):
        return AgentDecision(
            action="list_available_courses",
            course_id="ALL",
            target_subject="self",
            reason="Deterministic fallback: user asked for courses available to enroll.",
        )

    if any(w in text for w in ["taken", "enrolled", "completed", "my courses", "courses", "course"]):
        return AgentDecision(
            action="list_enrolled_courses",
            course_id="ALL",
            target_subject=target_subject,
            reason="Deterministic fallback: user asked for enrolled/taken courses.",
        )

    return AgentDecision(
        action="list_available_courses",
        course_id="ALL",
        target_subject="self",
        reason="Deterministic fallback: default to available course catalog.",
    )


def decide_action(message: str) -> AgentDecision:
    if not settings.use_llm:
        return fallback_decide(message)

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=message)],
                )
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
            ),
        )

        if not response.text:
            raise ValueError("LLM returned empty response")

        data = json.loads(response.text)
        action = data.get("action", "").strip()
        course_id = data.get("course_id", "ALL") or "ALL"
        target_subject = data.get("target_subject", "self") or "self"
        reason = data.get("reason", "Intent classified by LLM")

        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"LLM returned unsupported action: {action}")

        if action in {"list_available_courses", "list_enrolled_courses", "delete_course_history"}:
            course_id = "ALL"

        if action == "enroll_course" and not course_id:
            course_id = "UNKNOWN"

        return AgentDecision(
            action=action,
            course_id=course_id,
            target_subject=target_subject,
            reason=reason,
        )

    except Exception as exc:
        fallback = fallback_decide(message)
        fallback.reason = f"LLM classification failed; fallback used. Error: {str(exc)}"
        return fallback
