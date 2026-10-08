# P7 Voice backends

## Default: legacy

```bash
LUKA_VOICE_BACKEND=legacy
```

This preserves the accepted Luka voice stack:
- sherpa-onnx keyword spotting;
- Silero VAD / existing endpoint logic;
- local SenseVoice via sherpa-onnx;
- existing VITS/Kokoro/Matcha TTS pipeline;
- voiceprint/DOA/product command routing.

No accepted product behavior is deleted.

## Optional: drobotics

```bash
LUKA_VOICE_BACKEND=drobotics
NX_MIC=...
NX_SPEAKER=...
bash system/bringup/start_nx_voice.sh
```

This starts mutually exclusive official components:
- `sensevoice_ros2` owns microphone capture;
- `hobot_tts` owns TTS playback;
- `voice_suite_bridge` gates ASR behind the official wake event, forwards
  accepted speech to `/voice/recognized_text` and `/llm_command`, and maps
  explicit LLM speech statuses to `/tts_text`.

The D-Robotics backend is experimental until microphone-array wake-event
behavior and TTS quality are validated on the physical S100.

## Why not run both capture stacks

Both the current Luka gateway and `sensevoice_ros2` open ALSA capture. Running
both against the same hardware can cause exclusive-device conflicts, duplicate
ASR and undefined wake behavior. The backend selector intentionally prevents
that architecture.

## AEC / barge-in

P7 does not claim full-duplex acoustic echo cancellation. The current legacy
path still uses playback guarding. A future audio-frontend phase can insert
WebRTC AEC with a render reference without changing the Agent contract.


## L4 runtime contract

Both voice backends now expose the same structured interaction-state topic:

```text
/voice/runtime
```

States follow the xiaozhi-style interaction model:

```text
idle -> listening -> thinking -> speaking
                         ^          |
                         +----------+
                     barge-in / follow-up
```

The legacy Luka backend has real local playback-process visibility and can
perform generation-safe speech cancellation. Acoustic barge-in remains gated
behind `aec_full_duplex` plus a named AEC provider.

The D-Robotics backend does not currently expose a reliable hobot_tts
playback-drained signal. Its `speaking` duration is therefore an explicitly
marked estimate used for diagnostics/session state only. This is not evidence
of AEC or full-duplex support.
