# Voice Architecture Reference Lock

These sources are pinned for architecture comparison only.

| Project | Branch | SHA | Use in Luka |
|---|---|---|---|
| 78/xiaozhi-esp32 | main | `0d576d3d4c049c6f55eaf879725dc23e516511b4` | state machine, audio service, barge-in design |
| espressif/esp-skainet | master | `4f3d8252373fdbbec7c20add928ff084aeff4066` | AFE/KWS/VAD/pre-roll design |
| D-Robotics/xiaozhi-in-rdk | main | `ade6cd1cc25ee105dc7d0fee600c56b8dd8b4305` | actual RDK Linux/MCP integration |

Do not vendor ESP32 binaries or ESP-SR models into the RDK S100 runtime.
