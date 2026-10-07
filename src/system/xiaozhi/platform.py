from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class XiaozhiMode:
    name: str
    protocol: bool
    mcp: bool
    owns_audio: bool
    description: str

    def snapshot(self):
        return asdict(self)


MODES = {
    "off": XiaozhiMode(
        "off", False, False, False, "Xiaozhi integration disabled"
    ),
    "mcp_only": XiaozhiMode(
        "mcp_only",
        False,
        True,
        False,
        "Luka owns voice; official mcp_pipe exposes robot tools to Xiaozhi",
    ),
    "exclusive_remote": XiaozhiMode(
        "exclusive_remote",
        True,
        True,
        True,
        "Official RDK Xiaozhi client owns audio and runs MQTT/UDP protocol + MCP",
    ),
}


def get_mode(name: str) -> XiaozhiMode:
    key = str(name or "").strip().lower()
    if key not in MODES:
        raise ValueError(f"unsupported Xiaozhi mode: {key}")
    return MODES[key]
