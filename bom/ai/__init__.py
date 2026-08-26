""" Bomnado AI.

Everything that talks to the Claude API lives here. The rules:

- The AI acts through one tool surface (`bom.ai.tools`), as the requesting user, through the
  same validation and team checks as the rest of the app. It has no other access. The same
  tools serve the in-app chat (`bom.ai.chat`) and MCP clients (`bom.ai.mcp_server`).
- Every call is made with the user's own key (`bom.ai.client`), recorded on an `AIJob` with
  its token usage and cost, and anything it creates or changes is attributed in history
  and flagged for human review (`bom.ai.actions`).
"""
