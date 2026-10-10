"""FastMCP server exposing live Google Calendar, Docs, and Gmail tools."""

from integrations.google_mcp.tools import GoogleMcpTools

__all__ = ["GoogleMcpTools", "create_mcp_server", "mcp"]


def __getattr__(name: str):
    if name in {"mcp", "create_mcp_server"}:
        from integrations.google_mcp import server as _server

        return getattr(_server, name)
    raise AttributeError(name)
