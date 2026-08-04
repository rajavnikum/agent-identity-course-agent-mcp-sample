# Using your own MCP server

1. Keep the conversational application as the MCP Host or integrate the client logic into your existing host.
2. Replace `mcp_server.py` with your MCP server endpoint/process.
3. Change `mcp_client.py` to the transport used by your MCP server.
4. Discover tools from the server with `tools/list` rather than maintaining a duplicate manual tool catalog.
5. Map the selected MCP tool to scopes and authorization-detail context.
6. Obtain the IBM Verify actor token for the registered agent.
7. Exchange subject and actor tokens immediately before the protected tool invocation when the operation context is known.
8. At a remote MCP HTTP server, validate the bearer token at the protected resource boundary.
9. Compare the authorized tool/action context to the actual `tools/call` request.
10. Execute the tool only after validation succeeds.
