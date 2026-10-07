# Luka × xiaozhi-in-rdk

Pinned upstream: `D-Robotics/xiaozhi-in-rdk@ade6cd1cc25ee105dc7d0fee600c56b8dd8b4305`.

## Architecture

```text
Xiaozhi Agent
   |
   | MCP WebSocket
   v
D-Robotics mcp_pipe.py
   |
   | stdio MCP
   v
luka_mcp_server.py
   |
   | localhost HTTP
   v
/api/assistant/tools
/api/assistant/execute
   |
   v
nx_assistant_tools
   |
   v
existing Luka safety/product stack
```

The MCP server has no ROS Twist publisher, Nav2 action client, DDSM serial
control or direct follow wheel output.

## Install upstream

Use the pinned Suite manifest or clone the exact commit:

```bash
git clone https://github.com/D-Robotics/xiaozhi-in-rdk.git
cd xiaozhi-in-rdk
git checkout ade6cd1cc25ee105dc7d0fee600c56b8dd8b4305
python3 -m pip install -r requirements.txt
```

## First run: status-only

Keep motion disabled.

```bash
export XIAOZHI_RDK_ROOT=/home/sunrise/xiaozhi-in-rdk
export MCP_ENDPOINT='ws://YOUR_XIAOZHI_MCP_ENDPOINT'
export LUKA_XIAOZHI_ALLOW_MOTION=0

bash /home/sunrise/luka_ws/system/scripts/start_xiaozhi_mcp.sh
```

Expected available tools include status, destinations, follow status, object
location, stop robot and stop following. Motion requests return a permission
error.

## Controlled motion enable

Only after status-only MCP works and Luka navigation/following is independently
verified:

```bash
export LUKA_XIAOZHI_ALLOW_MOTION=1
bash /home/sunrise/luka_ws/system/scripts/start_xiaozhi_mcp.sh
```

Motion-capable tools still go through the Dashboard assistant generation token
and existing grounding/safety checks.

## Important

- `user_text` on motion MCP tools must be the original user's sentence.
- Destination/query must literally occur in that sentence where required.
- `stop_robot` and `stop_following` remain callable with motion disabled.
- `start_following` follows only the target already selected/verified by Luka.
  It never chooses a random person.
- Elevator is deliberately not exposed because the current S100 assistant tool
  layer still reports elevator as not connected.
- The official YOLOv8 MCP server is not enabled by this config; Luka already has
  its own S100 perception/object pipeline and should not run a duplicate camera
  detector by default.


## Motion environment precedence

The MCP config deliberately does not set `LUKA_XIAOZHI_ALLOW_MOTION`.
D-Robotics `mcp_pipe.py` copies the parent environment and then applies values
from the MCP config, so putting a hard-coded `0` in the config would override
an operator's later explicit `export LUKA_XIAOZHI_ALLOW_MOTION=1`.

Safety remains default-off because `LukaAssistantClient` treats an absent
variable as false. Only an explicit parent-shell value of `1` enables motion.
