# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Optional, Dict, Any

from config import settings


def build_agent_authorization_details(
    creator: str,
    affected_person: str,
    action: str,
    target_system: str,
    resource: str,
    course_id: str = "ALL",
    logged_in_subject: Optional[str] = None,
    tool_name: Optional[str] = None,
    downstream_system: Optional[str] = None,
) -> Dict[str, Any]:
    """
    UC2 RAR/authorization_details builder.

    targetSystem is the MCP server because the agent no longer calls the Course API directly.
    downstreamSystem records the final business system behind MCP for audit/policy context.
    """
    return {
        "type": settings.agent_adt_type,
        "courseId": course_id,
        "operationDetails": {
            "creator": creator,
            "affectedPerson": affected_person,
            "loggedInSubject": logged_in_subject or affected_person,
            "action": action,
            "targetSystem": target_system,
            "resource": resource,
            "toolName": tool_name or action,
            "downstreamSystem": downstream_system or settings.downstream_system,
        },
    }
