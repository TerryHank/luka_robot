# D-Robotics RDK S100 Suite Version Lock

Captured 2026-10-07.

| Component | Upstream branch | Locked commit |
|---|---|---|
| tros_person_following | develop | `202e8c8a04dc41e3d3771daa131b852cc24f7c0d` |
| mot / hobot_mot | develop | `0120205146d88c3474bfc2936522e349e169fa8d` |
| hobot_msgs / ai_msgs | develop | `ca63ebb7379862a6c307d17b0b86bd7096a1656d` |
| hobot_dnn | develop | `a5d6c3312315599b03d09ce5f00a8a9761702f12` |
| sensevoice_ros2 | develop | `9200ec9a3b10ec558423a086f96d21ac3f862a7b` |
| hobot_tts | develop | `ecb8ace02a2ada04a8cb311d4eb697ad41ad91ee` |
| hobot_xlm | develop | `cd9901f51cd3107b118fe2f8783c7c45af83d33f` |
| hobot_llamacpp | develop | `439f23f6c9b09eaebcf84027a0911c220fb4fb34` |
| rdk_model_zoo_s | s100 | `aeed911b157866e0e8a8efa6f134a8c93e731af0` |

Production must never float on `develop`. An upstream bump requires an explicit SHA change plus regression evidence.
