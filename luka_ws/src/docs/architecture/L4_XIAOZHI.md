# Xiaozhi layer

Luka treats Xiaozhi as two distinct capabilities instead of one opaque process.

## Protocol

The official `D-Robotics/xiaozhi-in-rdk` client implements the remote Xiaozhi
session using OTA-provided MQTT configuration plus encrypted UDP/Opus audio.
That client opens capture and playback itself, so Luka only permits it in the
`exclusive_remote` mode.

## MCP

The official `mcp_pipe.py` is used as the WebSocket <-> local MCP stdio
transport. The local server is `system/xiaozhi/luka_mcp_server.py`.

MCP tools now call `LukaAgentGateway.execute_tool()`, which delegates to the
existing localhost assistant safety API. MCP never imports Nav2, Twist or DDSM.

## Modes

```text
mcp_only (default)
Luka Audio Frontend -> Voice Runtime -> local Agent
Xiaozhi service ---------------------> MCP pipe -> Luka Agent Gateway -> L3
(no Xiaozhi audio ownership)

exclusive_remote
xiaozhi-in-rdk -> MQTT + UDP/Opus -> Xiaozhi service
       |
       +---------- mcp_pipe -> Luka Agent Gateway -> L3
(official client exclusively owns microphone/speaker)
```

Start:

```bash
# Recommended robot integration
export LUKA_XIAOZHI_MODE=mcp_only
export MCP_ENDPOINT=ws://...
bash system/scripts/start_xiaozhi_platform.sh

# Protocol compatibility / remote Xiaozhi test; stop Luka voice first
export LUKA_XIAOZHI_MODE=exclusive_remote
export MCP_ENDPOINT=ws://...
bash system/scripts/start_xiaozhi_platform.sh
```

The platform intentionally does not run the official client's PyAudio capture
beside Luka's KWS/VAD capture.
