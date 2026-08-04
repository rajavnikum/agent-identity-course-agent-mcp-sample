# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from mcp_gateway import invoke_mcp_tool


mcp = FastMCP("course-mcp-server")


def _execute(
    *,
    tool_name: str,
    delegated_token: str,
    course_id: str,
    requested_subject: str,
    logged_in_subject: str,
) -> str:
    """Run IBM Verify-aware validation before executing the requested course tool."""
    result = invoke_mcp_tool(
        delegated_token=delegated_token,
        tool_name=tool_name,
        course_id=course_id,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )
    return json.dumps(result)


@mcp.tool()
def list_available_courses(
    delegated_token: str,
    course_id: str = "ALL",
    requested_subject: str = "self",
    logged_in_subject: str = "self",
) -> str:
    """List courses available for enrollment after delegated-token validation."""
    return _execute(
        tool_name="list_available_courses",
        delegated_token=delegated_token,
        course_id=course_id,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )


@mcp.tool()
def list_enrolled_courses(
    delegated_token: str,
    course_id: str = "ALL",
    requested_subject: str = "self",
    logged_in_subject: str = "self",
) -> str:
    """List the signed-in subject's enrolled courses after delegated-token validation."""
    return _execute(
        tool_name="list_enrolled_courses",
        delegated_token=delegated_token,
        course_id=course_id,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )


@mcp.tool()
def enroll_course(
    delegated_token: str,
    course_id: str,
    requested_subject: str,
    logged_in_subject: str,
) -> str:
    """Enroll the signed-in subject in a course after delegated-token validation."""
    return _execute(
        tool_name="enroll_course",
        delegated_token=delegated_token,
        course_id=course_id,
        requested_subject=requested_subject,
        logged_in_subject=logged_in_subject,
    )


if __name__ == "__main__":
    # STDIO is used for this local tutorial. Never log protocol data to stdout.
    mcp.run(transport="stdio")
