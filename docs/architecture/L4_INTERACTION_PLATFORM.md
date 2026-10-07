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
