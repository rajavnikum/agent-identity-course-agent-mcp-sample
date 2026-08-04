# MCP Client, Server, and Tool Call Flow

## Roles

```text
app.py        = MCP Host / conversational agent
mcp_client.py = MCP Client
mcp_server.py = MCP Server
mcp_gateway.py= MCP server-side authorization and execution adapter
```

## Discovery

```text
GET /mcp/tools
 -> app.mcp_tools()
 -> mcp_client.list_mcp_tools()
 -> ClientSession.initialize()
 -> ClientSession.list_tools()
 -> MCP tools/list
 -> mcp_server.py returns registered @mcp.tool() definitions
```

## Invocation

```text
POST /chat
 -> decide_action()
 -> build_agent_authorization_details()
 -> get_actor_token()
 -> token_exchange()
 -> mcp_client.call_mcp_tool()
 -> ClientSession.list_tools()
 -> ClientSession.call_tool(tool_name, arguments)
 -> MCP tools/call
 -> mcp_server.py @mcp.tool() handler
 -> mcp_gateway.invoke_mcp_tool()
 -> delegated-token and ADT validation
 -> course operation
 -> MCP result
```

## Tools

| MCP tool | Registered function | Business scope |
|---|---|---|
| `list_available_courses` | `mcp_server.list_available_courses()` | `course.read` |
| `list_enrolled_courses` | `mcp_server.list_enrolled_courses()` | `course.read` |
| `enroll_course` | `mcp_server.enroll_course()` | `course.enroll` |

## Security sequence

The MCP client does not call the selected tool immediately after the LLM chooses it.

```text
LLM selects tool
 -> build operation context
 -> actor token
 -> IBM Verify token exchange
 -> delegated token
 -> MCP tools/list
 -> MCP tools/call
 -> server validates delegated context against actual tool
 -> execute
```

The local tutorial uses STDIO and passes the delegated token in the tool arguments. For a remote MCP HTTP deployment, move bearer-token handling to the MCP HTTP resource boundary and use the `Authorization` header according to the MCP authorization model.
