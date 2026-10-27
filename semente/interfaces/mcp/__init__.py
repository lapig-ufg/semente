"""MCP interface: wraps a remote A2A agent as a single MCP tool."""

from semente.interfaces.mcp.server import A2AClientError, build_server, run_stdio, send_message

__all__ = ["A2AClientError", "build_server", "run_stdio", "send_message"]
