# ASR / TTS backend layer

L4 does not let the rest of the robot depend on one ASR or TTS implementation.

Profiles:

| profile | ASR | TTS | transport | audio ownership |
|---|---|---|---|---|
| `luka_local` | sherpa-onnx SenseVoice | local sherpa-onnx TTS | in-process | Luka VoiceGateway |
| `drobotics` | `sensevoice_ros2` | `hobot_tts` | ROS2 topics | D-Robotics nodes |
| `xiaozhi_remote` | Xiaozhi server | Xiaozhi server | MQTT + UDP/Opus | exclusive Xiaozhi client |

The current production Luka path now calls `LocalSenseVoiceASR.transcribe()`
instead of constructing SenseVoice directly inside the command recognizer.
Local TTS is similarly wrapped by `LocalTTSBackend`.

The D-Robotics backend remains process-external because the official nodes own
capture/playback. It still reports the same `speech_backend` structure in
`/voice/runtime`.

`xiaozhi_remote` is intentionally marked as an exclusive-audio profile; it
must not run alongside the local Luka capture path.
