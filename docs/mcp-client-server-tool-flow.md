# MCP client, server and protected tools

## Runtime flow

```mermaid
flowchart TD
    H["app.py: chat"] --> I["llm_agent.py: decide action"]
    I --> R["Resolve subject and build authorization details"]
    R --> V["verify_oauth.py: actor token + Token Exchange"]
    V --> C["mcp_client.py: initialize and discover tools"]
    C --> Q{"Requested tool published?"}
    Q -->|"No"| U["Unknown-tool denial"]
    Q -->|"Yes"| M["MCP tools/call: registered server handler"]
    M --> G["mcp_gateway.py: validate token and operation"]
    G --> P{"Authorization passed?"}
    P -->|"No"| D["Return scope or context denial"]
    P -->|"Yes"| E["Execute permitted tool"]
    E --> O["MCP result to application and user"]
```

## Protected token flow

```mermaid
flowchart TD
    H["Human subject access token"] --> S["IBM Verify STS"]
    A["Agent actor access token"] --> S
    R["Selected tool authorization details"] --> S
    S --> T["Delegated JWT: audience course-mcp-server"]
    T --> M["MCP tools/call"]
    M --> Q{"Signature, audience, scope and context valid?"}
    Q -->|"Yes"| E["Execute selected tool"]
    Q -->|"No"| D["Deny before execution"]
```

## Published tools and required scopes

| MCP tool | Handler | Required business scope |
|---|---|---|
| `list_available_courses` | `mcp_server.list_available_courses()` | `course.read` |
| `list_enrolled_courses` | `mcp_server.list_enrolled_courses()` | `course.read` |
| `enroll_course` | `mcp_server.enroll_course()` | `course.enroll` |
| `delete_course_history` | `mcp_server.delete_course_history()` | `course.delete` |

All four also require `mcp.tools.invoke`. The supplied Verify mapping withholds `course.delete`, so the delete test reaches the handler and fails its scope check.

## Delete denial

```mermaid
flowchart TD
    U["Delete my course history"] --> H["Host builds delete_course_history context"]
    H --> V["Verify Token Exchange"]
    V --> T["Delegated scope: mcp.tools.invoke"]
    T --> C["MCP client discovers published delete tool"]
    C --> M["tools/call: delete_course_history"]
    M --> G["Gateway requires mcp.tools.invoke + course.delete"]
    G --> Q{"course.delete present?"}
    Q -->|"No: supplied mapping"| D["403: missing course.delete; no deletion"]
    Q -->|"Yes: separate explicit grant"| E["Validate identity and context before local deletion"]
```

The local tutorial uses STDIO and passes the delegated token in tool arguments. Server diagnostics go to stderr; stdout carries MCP protocol messages. Local enrollment writes persist in SQLite across subprocesses.

For remote MCP HTTP deployments, validate bearer tokens at the HTTP resource boundary and use the Authorization header.
