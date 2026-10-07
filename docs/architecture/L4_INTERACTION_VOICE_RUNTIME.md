# L4 Interaction Voice Runtime Reference

Branch: `feat/l4-voice-runtime-xiaozhi-skainet`

Reference-only upstreams:

- `78/xiaozhi-esp32@0d576d3d4c049c6f55eaf879725dc23e516511b4`
- `espressif/esp-skainet@4f3d8252373fdbbec7c20add928ff084aeff4066`
- Runtime Xiaozhi transport remains `D-Robotics/xiaozhi-in-rdk` through the
  existing Luka MCP bridge.

These repositories are architectural references, not S100 runtime
dependencies. ESP32/ESP-SR binaries and algorithms are not copied to ARM64.

## Target L4 architecture

```text
                              L4 Interaction
                                     |
             +-----------------------+-----------------------+
             |                                               |
   78/xiaozhi-esp32 design                         D-Robotics runtime
             |                                               |
             v                                               v
   explicit voice state machine                     xiaozhi-in-rdk
   audio service / queues                           MCP pipe
   speaking -> listening                            TROS / Linux
   wake callbacks                                   S100 integration
             |                                               |
             +-----------------------+-----------------------+
                                     |
                         Luka Voice Runtime
                                     |
                 +-------------------+-------------------+
                 |                   |                   |
                 v                   v                   v
          Audio Frontend       Session/FSM          Luka MCP
          KWS/VAD/AEC          barge-in policy      Robot tools
                 |
        ESP-Skainet concepts
        AFE -> WakeNet -> VAD
        VAD cache / pre-roll
                                     |
============================== L3 Mission ==============================
                Hotel / Patrol / Floor / Workflow
============================== L2 Behavior =============================
                    Follow / Find / Dock / Nav2
============================== L1 Control ==============================
                         Safety -> DDSM
```

## What is copied conceptually

### From 78/xiaozhi-esp32

1. A strict explicit state machine instead of inferring state from unrelated
   booleans.
2. A separate audio-service contract: capture/processing and playback/session
   orchestration are different responsibilities.
3. `speaking -> listening` is a first-class transition for barge-in.
4. Wake/VAD/playback events are callbacks into the session state machine rather
   than direct robot actions.
5. Playback cancellation has a generation/interrupt boundary; stale speech
   must not continue after a new user turn.

### From ESP-Skainet

1. Treat the acoustic front end as its own layer:
   `AEC/NS -> KWS -> VAD/command capture`.
2. Keep a VAD pre-roll/cache so the first spoken syllable is not lost while VAD
   establishes continuous speech.
3. Expose acoustic capabilities explicitly. Barge-in must not be enabled merely
   because a KWS exists; it requires an echo-controlled capture path.
4. Wake-word and VAD engines are replaceable behind interfaces.

## Luka-specific decisions

- Existing sherpa-onnx KWS remains the production KWS.
- Existing SenseVoice remains available for ASR.
- Existing TTS backends remain available.
- D-Robotics `xiaozhi-in-rdk` remains the Linux Xiaozhi/MCP path.
- ESP-Skainet is **not** compiled for S100; its AFE/WakeNet/MultiNet design is
  used as an abstraction reference.
- Current USB-mic playback guard remains the default:
  `duplex_mode=guarded_half_duplex`.
- Automatic wake-during-TTS is permitted only when the operator explicitly
  selects `duplex_mode=aec_full_duplex`, asserting the configured capture
  device is already echo-controlled.
- Manual/UI speech interruption is allowed without claiming acoustic AEC.
- No L4 component gains Nav2, Twist, DDSM or motor authority. Xiaozhi still
  calls Luka MCP/Assistant tools, which flow through L3-L1 safety policy.

## Runtime state model

```text
STARTING
   |
   v
  IDLE <-------------------------------+
   |                                   |
 wake                                  | session end / one-shot reply drained
   v                                   |
LISTENING ---- utterance final ----> THINKING
   ^                                   |
   |                                   | response
   |                                   v
   +----------- barge-in ----------- SPEAKING
   |                                   |
   +------ wake acknowledgement -------+
```

Invalid transitions fail closed and are published in runtime diagnostics.

## Rollout

Phase A (this branch):
- explicit FSM and audio-front-end capability policy;
- structured `/voice/runtime` diagnostics;
- safe manual speech interrupt;
- optional AEC-gated wake-during-TTS plumbing;
- preserve guarded half-duplex defaults.

Phase B (physical S100):
- feed an actual echo-controlled 16 kHz mono capture source;
- measure false wake during local TTS;
- verify VAD pre-roll and first-syllable retention;
- verify wake-during-TTS interrupts playback;
- verify continuous dialogue timeout and recovery.

Phase C:
- only after AEC measurements pass, enable full-duplex profile by default.

## Non-claims

This code does not claim that the S100 currently has a working WebRTC/ESP AEC
implementation. Selecting `aec_full_duplex` is an operator assertion that the
configured capture source is already echo-controlled.
