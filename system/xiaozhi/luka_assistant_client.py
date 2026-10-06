"""HTTP-only client for Luka's existing assistant safety gateway."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


MOTION_TOOLS = {
    "navigate",
    "patrol_start",
    "find_object",
    "object_bring",
    "localization_auto",
    "follow_start",
}
SAFE_STOP_TOOLS = {"cancel_all", "patrol_stop", "follow_stop"}


def env_enabled(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


class LukaAssistantClient:
    def __init__(self, base_url=None, allow_motion=None, timeout=25.0):
        self.base_url = (
            base_url or os.getenv("LUKA_ASSISTANT_BASE", "http://127.0.0.1:8503")
        ).rstrip("/")
        self.allow_motion = (
            env_enabled("LUKA_XIAOZHI_ALLOW_MOTION")
            if allow_motion is None else bool(allow_motion)
        )
        self.timeout = float(timeout)

    def _json(self, path, body=None):
        data = None if body is None else json.dumps(
            body, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("error") or str(payload)
            except Exception:
                message = f"HTTP {exc.code}"
            raise ValueError(message) from exc

    def tools(self):
        payload = self._json("/api/assistant/tools")
        tools = payload.get("tools") or {}
        if not isinstance(tools, dict):
            raise RuntimeError("invalid Luka assistant tool catalog")
        generation = payload.get("generation")
        if type(generation) is not int:
            raise RuntimeError("invalid Luka assistant generation token")
        return tools, generation

    def execute(self, tool, arguments=None, source=""):
        tool = str(tool or "").strip()
        arguments = dict(arguments or {})
        source = str(source or "").strip()
        if not 1 <= len(source) <= 1000:
            raise ValueError("source must contain the original user request")
        catalog, generation = self.tools()
        if tool not in catalog:
            raise ValueError(f"Luka tool is not available: {tool}")
        if tool in MOTION_TOOLS and not self.allow_motion:
            raise PermissionError(
                "Xiaozhi motion tools are disabled; set "
                "LUKA_XIAOZHI_ALLOW_MOTION=1 only after dry-run validation"
            )
        body = {
            "tool": tool,
            "arguments": arguments,
            "source": source,
        }
        if tool in MOTION_TOOLS or tool in SAFE_STOP_TOOLS:
            body["generation"] = generation
        result = self._json("/api/assistant/execute", body)
        if result.get("ok") is not True:
            raise RuntimeError(result.get("error") or "Luka assistant rejected tool")
        return {
            "success": True,
            "tool": tool,
            "message": str(result.get("message") or ""),
        }
