#!/usr/bin/env bash
# Source this file from start_nx_voice.sh.
#
# Profiles:
#   guarded       - use the hardware devices supplied by NX_MIC/NX_SPEAKER.
#   pulse_webrtc  - create a PulseAudio/PipeWire-Pulse WebRTC echo-cancel
#                   virtual source/sink and route arecord/aplay through it.
#
# module-echo-cancel pairs playback and capture around the same WebRTC APM.
# The WebRTC implementation in PulseAudio enables noise suppression by default;
# we still pass it explicitly so runtime diagnostics reflect the actual profile.

case "${LUKA_AUDIO_FRONTEND:-guarded}" in
  guarded)
    export LUKA_VOICE_DUPLEX_MODE="${LUKA_VOICE_DUPLEX_MODE:-guarded_half_duplex}"
    export LUKA_VOICE_AEC_PROVIDER="${LUKA_VOICE_AEC_PROVIDER:-none}"
    export LUKA_VOICE_NS_PROVIDER="${LUKA_VOICE_NS_PROVIDER:-none}"
    export LUKA_VOICE_NS="${LUKA_VOICE_NS:-false}"
    ;;
  pulse_webrtc)
    command -v pactl >/dev/null 2>&1 || {
      echo "pulse_webrtc requires pactl (PulseAudio or PipeWire Pulse compatibility)" >&2
      return 11 2>/dev/null || exit 11
    }
    arecord -L 2>/dev/null | grep -qx 'pulse' || {
      echo "ALSA pulse capture plugin is missing; install libasound2-plugins" >&2
      return 12 2>/dev/null || exit 12
    }
    aplay -L 2>/dev/null | grep -qx 'pulse' || {
      echo "ALSA pulse playback plugin is missing; install libasound2-plugins" >&2
      return 13 2>/dev/null || exit 13
    }

    source_name="${LUKA_AEC_SOURCE_NAME:-luka_aec_source}"
    sink_name="${LUKA_AEC_SINK_NAME:-luka_aec_sink}"

    source_master="${LUKA_AEC_SOURCE_MASTER:-$(pactl get-default-source 2>/dev/null || true)}"
    sink_master="${LUKA_AEC_SINK_MASTER:-$(pactl get-default-sink 2>/dev/null || true)}"

    if [ -z "$source_master" ] || [ "$source_master" = "$source_name" ]; then
      source_master="$(pactl list short sources | awk -v n="$source_name" '$2 != n && $2 !~ /\.monitor$/ {print $2; exit}')"
    fi
    if [ -z "$sink_master" ] || [ "$sink_master" = "$sink_name" ]; then
      sink_master="$(pactl list short sinks | awk -v n="$sink_name" '$2 != n {print $2; exit}')"
    fi
    [ -n "$source_master" ] || {
      echo "No physical Pulse source found for AEC" >&2
      return 14 2>/dev/null || exit 14
    }
    [ -n "$sink_master" ] || {
      echo "No physical Pulse sink found for AEC" >&2
      return 15 2>/dev/null || exit 15
    }

    if ! pactl list short sources | awk '{print $2}' | grep -qx "$source_name"; then
      module_id="$(pactl load-module module-echo-cancel         source_master="$source_master" sink_master="$sink_master"         source_name="$source_name" sink_name="$sink_name"         rate=16000 channels=1 aec_method=webrtc         aec_args='noise_suppression=1 transient_noise_suppression=1 analog_gain_control=0 digital_gain_control=0 voice_detection=0')" || {
          echo "Failed to load module-echo-cancel with WebRTC APM" >&2
          return 16 2>/dev/null || exit 16
        }
      runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
      mkdir -p "$runtime_dir/luka"
      printf '%s\n' "$module_id" > "$runtime_dir/luka/pulse_echo_cancel.module"
    fi

    pactl set-default-source "$source_name"
    pactl set-default-sink "$sink_name"

    export NX_MIC=pulse
    export NX_SPEAKER=pulse
    export LUKA_VOICE_DUPLEX_MODE=aec_full_duplex
    export LUKA_VOICE_AEC_PROVIDER=pulseaudio_webrtc
    export LUKA_VOICE_NS_PROVIDER=pulseaudio_webrtc
    export LUKA_VOICE_NS=true
    ;;
  *)
    echo "Unsupported LUKA_AUDIO_FRONTEND=$LUKA_AUDIO_FRONTEND (guarded|pulse_webrtc)" >&2
    return 10 2>/dev/null || exit 10
    ;;
esac
