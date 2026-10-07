# L4 Interaction Platform quick start

## 1. Build

```bash
cd /home/sunrise/luka_ws
git fetch origin
git checkout feat/l4-voice-runtime-xiaozhi-skainet
git pull
colcon build --packages-select nav_llm_agent
source install/setup.bash
```

## 2. Safe default: Luka local voice

```bash
export NX_MIC=<your-alsa-capture-device>
export NX_SPEAKER=<your-alsa-playback-device>
export LUKA_AUDIO_FRONTEND=guarded
export LUKA_VOICE_BACKEND=legacy

bash system/bringup/start_nx_agent.sh
# another terminal/service:
bash system/bringup/start_nx_voice.sh
```

Observe:

```bash
ros2 topic echo /voice/runtime
ros2 topic echo /luka/interaction/platform_status
```

## 3. WebRTC AEC + NS

First list the Pulse devices:

```bash
pactl get-default-source
pactl get-default-sink
pactl list short sources
pactl list short sinks
```

Then:

```bash
export NX_MIC=<physical ALSA capture; required before profile setup>
export NX_SPEAKER=<physical ALSA playback; required before profile setup>
export LUKA_AUDIO_FRONTEND=pulse_webrtc

# Optional explicit Pulse masters:
export LUKA_AEC_SOURCE_MASTER=<pulse-source>
export LUKA_AEC_SINK_MASTER=<pulse-sink>

bash system/bringup/start_nx_voice.sh
```

The helper creates `luka_aec_source` and `luka_aec_sink`, routes the existing
voice process through ALSA `pulse`, and reports
`aec_provider=pulseaudio_webrtc` and `ns_provider=pulseaudio_webrtc`.

Do not mark full-duplex accepted until the physical checklist passes.

## 4. Xiaozhi MCP with Luka voice (recommended)

```bash
export MCP_ENDPOINT=ws://<xiaozhi-mcp-endpoint>
export LUKA_XIAOZHI_MODE=mcp_only
bash system/scripts/start_xiaozhi_platform.sh
```

This does not open another microphone.

Motion tools remain off unless explicitly enabled after dry-run:

```bash
export LUKA_XIAOZHI_ALLOW_MOTION=1
```

## 5. Official Xiaozhi Protocol compatibility mode

Stop Luka/D-Robotics voice capture first, then:

```bash
export XIAOZHI_RDK_ROOT=/home/sunrise/xiaozhi-in-rdk
export MCP_ENDPOINT=ws://<xiaozhi-mcp-endpoint>
export LUKA_XIAOZHI_MODE=exclusive_remote
bash system/scripts/start_xiaozhi_platform.sh
```

This starts both the official MQTT + UDP/Opus client and official MCP pipe.
The official client exclusively owns microphone/speaker.

## 6. Read-only platform acceptance

```bash
bash system/scripts/l4_interaction_preflight.sh
```

This command reads nodes/topics/status only. It sends no MCP tool, Nav2 goal,
Twist or DDSM command.
