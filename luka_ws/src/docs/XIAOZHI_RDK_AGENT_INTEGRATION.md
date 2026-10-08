# Luka × D-Robotics Xiaozhi Integration Plan

Branch: `feat/xiaozhi-rdk-agent-integration`

Pinned upstream:
`D-Robotics/xiaozhi-in-rdk@ade6cd1cc25ee105dc7d0fee600c56b8dd8b4305`

## Goal

Integrate Xiaozhi as an optional Agent/MCP surface without replacing Luka's
existing product safety and robot-control stack.

```text
Xiaozhi cloud / Agent
        |
        v
D-Robotics mcp_pipe.py
        |
        v
Luka MCP Server (stdio)
        |
        v
http://127.0.0.1:8503/api/assistant/*
        |
        v
nx_assistant_tools allowlist + grounding + generation token
        |
        +--> navigation / patrol / object memory / follow / stop
        |
        v
existing Luka safety chain
```

## Non-negotiable boundaries

1. Xiaozhi must never publish `cmd_vel`, Nav2 goals, DDSM commands, or follow
   wheel commands directly.
2. Robot actions must go through Luka's existing
   `/api/assistant/tools` + `/api/assistant/execute` path.
3. Existing local voice frontend remains available; this integration does not
   delete sherpa KWS, current ASR/TTS, or voice FSM.
4. Motion-capable MCP tools are disabled by default with
   `LUKA_XIAOZHI_ALLOW_MOTION=0`.
5. Stop/cancel remains callable even when motion is disabled.
6. Motion tools require the caller to pass the original user utterance as
   `user_text`; the existing assistant API performs its normal grounding
   checks again.
7. The dashboard assistant generation token is fetched immediately before a
   motion call so a joystick/stop/new-command invalidation still cancels stale
   requests.
8. Elevator is not exposed to Xiaozhi yet because the current S100
   `nx_assistant_tools` explicitly marks elevator/autonomous mapping as not
   connected. Do not bypass this product restriction.
9. Existing D-Robotics YOLO MCP is not enabled by default because Luka already
   has the richer S100 perception/object stack; duplicated camera inference is
   avoided.

## Initial MCP tools

Read/status:
- robot status
- destinations
- localization status
- services/functions status
- patrol route
- follow status
- object location/history status

Safe stop:
- stop all navigation/patrol/search
- stop following

Opt-in motion (`LUKA_XIAOZHI_ALLOW_MOTION=1`):
- navigate to an existing named destination
- start one-pass patrol
- start following the already selected/verified person
- bring the user to an already found object
- automatic relocalization

## Validation

- Static test: MCP server source contains no ROS `Twist`, Nav2 action client,
  serial motor API, or DDSM control.
- Pure tests: motion default-off, cancel default-on, generation token handling,
  source/target grounding requirements.
- Dashboard tests: follow tools reuse `FollowController` and
  `FollowAcquisition`; no parallel follow controller is introduced.
- Board test: first run MCP with motion disabled, verify tool listing/status,
  then explicitly arm motion in a controlled environment.


## Implementation status

Repository-side implementation:

- [x] Pin official `xiaozhi-in-rdk` commit.
- [x] Add Luka FastMCP stdio server.
- [x] Reuse official D-Robotics `mcp_pipe.py`.
- [x] Route all robot tools through localhost `/api/assistant/*`.
- [x] Default Xiaozhi motion gate to OFF.
- [x] Keep stop/cancel callable with motion gate OFF.
- [x] Add follow status/start/stop to the existing Assistant allowlist.
- [x] Include follow start/stop in Assistant generation invalidation.
- [x] Keep elevator and duplicate official YOLO MCP disabled.
- [x] Add read-only MCP/Dashboard preflight script.
- [x] Match upstream FastMCP stdio transport explicitly.

Physical S100 validation still required:

- [ ] Install the pinned `xiaozhi-in-rdk` Python dependencies on the S100.
- [ ] Configure the real `MCP_ENDPOINT` from the Xiaozhi service.
- [ ] Run `bash system/scripts/test_xiaozhi_mcp_readonly.sh`.
- [ ] Start `mcp_pipe.py` with `LUKA_XIAOZHI_ALLOW_MOTION=0`.
- [ ] Confirm Xiaozhi can call read-only status/destination/follow-status tools.
- [ ] Confirm motion tools are rejected while motion is disabled.
- [ ] Confirm `stop_robot` and `stop_following` work while motion is disabled.
- [ ] In a controlled test area, explicitly set
      `LUKA_XIAOZHI_ALLOW_MOTION=1`.
- [ ] With an already selected/verified person, test `start_following`.
- [ ] Test target loss/ID change/obstacle causes the existing Luka follow
      safety system to stop rather than switch targets.
- [ ] Test one named-destination navigation command.
- [ ] Confirm joystick/stop increments generation and invalidates a stale
      Xiaozhi motion request.

## Trust note

The MCP `user_text` argument is supplied by the Xiaozhi Agent and therefore is
not a cryptographic proof of the raw ASR transcript. The Dashboard still
re-runs its normal grounding checks, but the hard safety boundary for remote
motion remains the operator-controlled `LUKA_XIAOZHI_ALLOW_MOTION` gate plus
the existing localization/lidar/follow/base safety layers. Keep motion disabled
unless remote-Agent motion is intentionally being tested or used.
