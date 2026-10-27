"""``semente mcp`` — expose a remote A2A agent as a single MCP tool (stdio)."""

from __future__ import annotations

import sys
from typing import Optional


def cmd_mcp(url: str, name: Optional[str] = None, api_key: Optional[str] = None) -> int:
    try:
        from semente.interfaces.mcp import run_stdio
        import mcp  # noqa: F401
    except ImportError:
        print(
            "error: the MCP SDK is not installed. Run: pip install 'semente-agents[mcp]'",
            file=sys.stderr,
        )
        return 1
    # stdout belongs to the MCP protocol: every message goes to stderr.
    print(f"[semente mcp] wrapping the A2A agent at {url} (stdio)", file=sys.stderr)
    run_stdio(url, name=name, api_key=api_key)
    return 0
