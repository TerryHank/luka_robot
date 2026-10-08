# Audio Frontend profiles

Luka now has a real L4 acoustic-front-end boundary.

## guarded (default)

```text
hardware mic -> sherpa KWS -> Silero/sherpa VAD -> SenseVoice
local TTS -> hardware speaker
```

Capture is suspended while local TTS is playing. This is the safest default
when there is no verified echo canceller.

## pulse_webrtc

```text
physical source ------------------------+
                                        |
physical sink <- luka_aec_sink <--- WebRTC APM
                                        |
                         luka_aec_source
                             |  AEC + NS
                             v
                         arecord pulse
                             |
                      KWS -> VAD -> ASR
```

The profile uses `module-echo-cancel` through PulseAudio or PipeWire's Pulse
compatibility layer. Both expose `source_master`, `sink_master`,
`source_name`, `sink_name`, `aec_method` and `aec_args`.

Enable:

```bash
export LUKA_AUDIO_FRONTEND=pulse_webrtc
# Optional when the current Pulse defaults are not the intended hardware:
export LUKA_AEC_SOURCE_MASTER=<physical-source-name>
export LUKA_AEC_SINK_MASTER=<physical-sink-name>
bash system/bringup/start_nx_voice.sh
```

The startup helper creates `luka_aec_source` and `luka_aec_sink`, sets them
as Pulse defaults, and points the existing ALSA `pulse` plugin at them.

This makes AEC/NS deployable, but **physical acceptance is still required**:
speaker/microphone geometry, USB clock drift, room reverberation and volume can
all affect cancellation quality.
