# L4 Interaction Platform

The branch now implements the L4 platform as explicit runtime layers:

```text
Audio Frontend
  AEC / NS / KWS / VAD / pre-roll
          |
          v
Voice Runtime
  State Machine / Session / Continuous Dialogue
  Barge-in / Playback Generation
          |
          v
ASR / TTS Backend
  Luka local | D-Robotics | Xiaozhi remote
          |
          +-------------------------+
          |                         |
          v                         v
   Xiaozhi Protocol              Xiaozhi MCP
   MQTT + UDP/Opus              mcp_pipe + FastMCP
          |                         |
          +------------+------------+
                       |
                       v
                 Agent Gateway
       /luka/interaction/agent_input
                       |
                       v
                 nav_llm_agent
                       |
=======================|=======================
                    L3 Mission
```

## Operational status

`interaction_status` publishes a read-only aggregate on:

```text
/luka/interaction/platform_status
```

It reports the configured audio frontend, voice backend and Xiaozhi mode plus
freshness for Voice Runtime, Interaction Agent Gateway and the existing agent.

## Authority boundary

The normalized text Agent Gateway contains no robot tool implementation.
Xiaozhi MCP tool calls use the localhost assistant safety API. Neither path can
publish Twist or call DDSM directly. L3 remains the first layer allowed to own
mission/capability execution.


## Agent Gateway has two transports

The architectural boundary is one logical gateway with two adapters:

```text
free-form text
  -> ROS envelope gateway
  -> /llm_voice_command
  -> nav_llm_agent

explicit Xiaozhi MCP tool call
  -> LukaAgentGateway
  -> localhost /api/assistant/tools + /api/assistant/execute
  -> capability/workflow validation
```

The MCP path does **not** bypass L3 policy: motion is disabled by default for
Xiaozhi, the tool must exist in the current catalog, original user text is
required for grounded motion tools, and the assistant API revalidates the
request before execution.
