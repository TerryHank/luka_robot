"""Xiaozhi-facing L4 tool gateway.

The MCP server talks to this object, not to ROS motion APIs. Tool execution is
still revalidated by Luka's localhost assistant API before reaching L3/L2.
"""
from __future__ import annotations

from luka_assistant_client import LukaAssistantClient


class LukaAgentGateway:
    def __init__(self, client=None):
        self.client = client or LukaAssistantClient()

    def execute_tool(self, tool: str, arguments=None, user_text: str = "") -> dict:
        result = self.client.execute(tool, arguments or {}, user_text)
        return {
            "origin": "xiaozhi_mcp",
            "kind": "tool_result",
            **result,
        }
