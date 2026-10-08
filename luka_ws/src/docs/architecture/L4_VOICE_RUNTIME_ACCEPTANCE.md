# L4 Voice Runtime — S100 Acceptance

This checklist validates the xiaozhi/ESP-Skainet-inspired L4 interaction
runtime. Repository implementation is not evidence of acoustic full-duplex.

## A. Default guarded mode

Environment:

```bash
export LUKA_VOICE_DUPLEX_MODE=guarded_half_duplex
export LUKA_VOICE_AEC_PROVIDER=none
```

- [ ] `bash system/scripts/test_l4_voice_runtime_readonly.sh` passes.
- [ ] `/voice/runtime` reports `guarded_half_duplex`.
- [ ] Local TTS blocks acoustic capture and does not self-trigger.
- [ ] "露卡" enters listening.
- [ ] VAD endpoint retains the beginning of the command.
- [ ] Hands-free follow-up window behaves as before this branch.
- [ ] `/voice/control interrupt` cancels queued/current speech without moving
      the robot.

## B. External AEC preparation

Do not enable full-duplex until the actual `NX_MIC` source has AEC/echo
control. Examples may include a validated USB DSP microphone or a Linux
WebRTC/PipeWire AEC capture source.

Record:

- Capture device:
- AEC implementation/provider:
- Reference/playback feed:
- Sample rate:
- Channels:
- Test room:
- Speaker volume:

- [ ] Near-end speech is intelligible while Luka TTS is playing.
- [ ] Residual Luka TTS does not repeatedly trigger KWS.
- [ ] Residual Luka TTS does not repeatedly trigger VAD.
- [ ] No clipping/AGC pumping makes ASR unusable.

## C. AEC full-duplex

Only after B passes:

```bash
export LUKA_VOICE_DUPLEX_MODE=aec_full_duplex
export LUKA_VOICE_AEC_PROVIDER=<validated-provider-name>
export LUKA_VOICE_BARGE_IN=true
```

- [ ] Runtime starts; `aec_full_duplex + none` is rejected.
- [ ] During idle/notification speech, saying "露卡" interrupts playback and
      moves `speaking -> listening`.
- [ ] During an active conversation, starting to speak triggers VAD barge-in
      without requiring the wake word again.
- [ ] Current TTS process stops promptly.
- [ ] Queued stale TTS is dropped by generation.
- [ ] A stale playback-drained event never resets the new user capture.
- [ ] First syllable after barge-in is retained.
- [ ] New ASR text belongs to the user, not Luka's own TTS.

## D. Architecture gate

- [ ] L4 Interaction contains no Nav2 action client.
- [ ] L4 Interaction contains no Twist publisher.
- [ ] L4 Interaction contains no DDSM/motor API.
- [ ] Xiaozhi robot actions still use Luka MCP -> Assistant API -> L3/L2/L1.
- [ ] Motion safety remains independent of voice state.

## Decision

- [ ] Guarded mode PASS
- [ ] Full-duplex PASS
- [ ] Full-duplex BLOCKED — keep guarded mode

Notes:


## E. Platform integration

- [ ] `interaction_agent_gateway` is online.
- [ ] `interaction_platform_status` is online.
- [ ] Local voice text reaches `/luka/interaction/agent_input`.
- [ ] D-Robotics voice text reaches the same input.
- [ ] Gateway emits normalized `luka.interaction.text.v1` envelopes.
- [ ] Duplicate transport delivery with the same turn ID is dropped.
- [ ] `mcp_only` does not open a second microphone.
- [ ] `exclusive_remote` refuses to start while Luka voice capture is active.
- [ ] Xiaozhi MCP motion remains disabled unless
      `LUKA_XIAOZHI_ALLOW_MOTION=1` is explicitly set.
- [ ] All L4 contract CI checks pass.
