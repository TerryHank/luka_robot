# Agent Gateway

`interaction_agent_gateway` is the single normalized text ingress from L4 to
the existing L3-capable `nav_llm_agent`.

```text
Local Voice ---------+
D-Robotics Voice ----+--> /luka/interaction/agent_input
Xiaozhi protocol ----+          |
App / Dashboard -----+          v
                         InteractionAgentGateway
                                  |
                                  | normalized envelope
                                  v
                         /llm_voice_command
                                  |
                                  v
                            nav_llm_agent
                                  |
                              L3 Mission
```

Envelope schema: `luka.interaction.text.v1`

Required semantic field:
- `text`

Normalized fields:
- `source`
- `session_id`
- `turn_id`
- `captured_at`
- optional `speaker`
- optional non-authoritative `metadata`

The gateway owns no capability registry, Nav2 action, Twist publisher or DDSM
API. It only validates ingress and de-duplicates transport retries. Motion/tool
authority remains below this boundary.
