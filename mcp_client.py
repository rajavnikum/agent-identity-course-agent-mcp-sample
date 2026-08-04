# Copyright IBM Corp. All Rights Reserved.
# #
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_SCRIPT = Path(__file__).with_name("mcp_server.py")


async def list_mcp_tools() -> Dict[str, Any]:
    """Connect to the course MCP server and discover tools via MCP tools/list."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.list_tools()
            return {
                "server": "course-mcp-server",
                "protocol_operation": "tools/list",
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.inputSchema,
                    }
                    for tool in response.tools
                ],
            }


async def call_mcp_tool(
    *,
    delegated_token: str,
    tool_name: str,
    course_id: str,
    requested_subject: str,
    logged_in_subject: str,
) -> Dict[str, Any]:
    """Invoke one registered MCP tool via MCP tools/call."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        env=None,
    )

    arguments = {
        "delegated_token": delegated_token,
        "course_id": course_id,
        "requested_subject": requested_subject,
        "logged_in_subject": logged_in_subject,
    }

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            available = {tool.name for tool in tools.tools}
            if tool_name not in available:
                return {
                    "status": "DENIED",
                    "http_status": 400,
                    "reason": f"MCP tool is not exposed by the server: {tool_name}",
                    "available_tools": sorted(available),
                }

            result = await session.call_tool(tool_name, arguments)
            texts: List[str] = []
            for item in result.content:
                text = getattr(item, "text", None)
                if text is not None:
                    texts.append(text)

            if not texts:
                return {
                    "status": "DENIED_OR_FAILED",
                    "http_status": 500,
                    "reason": "MCP server returned no text result.",
                }

            try:
                return json.loads(texts[0])
            except json.JSONDecodeError:
                return {
                    "status": "SUCCESS" if not result.isError else "DENIED_OR_FAILED",
                    "http_status": 200 if not result.isError else 500,
                    "message": "\n".join(texts),
                }
