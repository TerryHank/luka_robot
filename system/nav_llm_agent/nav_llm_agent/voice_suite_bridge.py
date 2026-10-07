"""Adapter for the optional D-Robotics SenseVoice + hobot_tts backend.

This node contains no robot action/service clients. It gates official ASR behind
an audio wake event and forwards accepted text to Luka's existing agent topics.
"""
from __future__ import annotations

import json
import threading
import time

import rclpy
from audio_msg.msg import SmartAudioData
from rclpy.node import Node
from std_msgs.msg import String
from nav_llm_agent.interaction import AudioFrontendPolicy, VoiceRuntime, VoiceState


def spoken_status(text):
    text = (text or "").strip()
    if text.startswith("speech:"):
        return text.partition(":")[2].strip()
    if text.startswith("chat_sentence:"):
        return text.partition(":")[2].strip()
    return ""


class DRoboticsVoiceSuiteBridge(Node):
    def __init__(self):
        super().__init__("drobotics_voice_suite_bridge")
        self.wake_word = str(
            self.declare_parameter("wake_word", "露卡").value)
        self.follow_up_timeout = float(
            self.declare_parameter("follow_up_timeout", 12.0).value)
        self.asr_topic = str(
            self.declare_parameter("asr_topic", "/asr_text").value)
        self.smart_topic = str(
            self.declare_parameter("smart_topic", "/audio_smart").value)
        self.tts_topic = str(
            self.declare_parameter("tts_topic", "/tts_text").value)
        self.tts_chars_per_second = max(
            2.0,
            float(self.declare_parameter("tts_chars_per_second", 5.0).value),
        )
        self.runtime = VoiceRuntime(
            AudioFrontendPolicy.build(
                duplex_mode="guarded_half_duplex",
                aec_provider="none",
                kws_engine="sensevoice_ros2",
                vad_engine="sensevoice_ros2",
                pre_roll_ms=600,
                barge_in_enabled=False,
            ),
            continuous_dialogue=True,
        )
        self.tts_generation = 0
        self.tts_timer = None

        self.command_pub = self.create_publisher(String, "/llm_command", 10)
        self.text_pub = self.create_publisher(
            String, "/voice/recognized_text", 10)
        self.status_pub = self.create_publisher(String, "/voice/status", 10)
        self.runtime_pub = self.create_publisher(String, "/voice/runtime", 10)
        self.tts_pub = self.create_publisher(String, self.tts_topic, 10)
        self.create_subscription(
            SmartAudioData, self.smart_topic, self.on_smart_audio, 10)
        self.create_subscription(
            String, self.asr_topic, self.on_asr, 10)
        self.create_subscription(
            String, "/llm_status", self.on_llm_status, 10)

        self.armed_until = 0.0
        self.last_text = ""
        self.last_text_at = 0.0
        self.runtime.ready()
        self.runtime_status("ready", backend="drobotics", playback="estimated")
        self.status("ready backend=drobotics gated=1")

    def status(self, text):
        self.status_pub.publish(String(data=str(text)))
        self.get_logger().info(str(text))

    def runtime_status(self, event, **details):
        payload = self.runtime.snapshot()
        payload["event"] = str(event)
        payload["backend"] = "drobotics"
        payload["playback_timing"] = "estimated"
        if details:
            payload["details"] = details
        self.runtime_pub.publish(
            String(data=json.dumps(payload, ensure_ascii=False, sort_keys=True))
        )

    def _finish_estimated_playback(self, generation):
        if generation != self.tts_generation:
            return
        state = self.runtime.playback_drained("response")
        self.runtime_status(
            "playback_drained",
            generation=generation,
            estimated=True,
        )
        if state is VoiceState.LISTENING:
            self.armed_until = max(
                self.armed_until,
                time.monotonic() + self.follow_up_timeout,
            )

    def _mark_estimated_playback(self, text):
        self.tts_generation += 1
        generation = self.tts_generation
        if self.tts_timer is not None:
            self.tts_timer.cancel()
        try:
            self.runtime.playback_started("response")
        except ValueError as exc:
            self.runtime_status("invalid_transition", error=str(exc))
        else:
            self.runtime_status(
                "playback_started",
                generation=generation,
                estimated=True,
            )
        duration = max(
            0.8,
            min(20.0, len(text) / self.tts_chars_per_second + 0.6),
        )
        self.tts_timer = threading.Timer(
            duration,
            self._finish_estimated_playback,
            args=(generation,),
        )
        self.tts_timer.daemon = True
        self.tts_timer.start()

    def on_smart_audio(self, msg):
        frame_type = int(msg.frame_type.value)
        event_type = int(msg.event_type.value)
        wake_event = (
            frame_type == 2 and event_type in (1, 2)
        )
        wake_command = (
            frame_type == 3
            and (msg.cmd_word or "").replace(" ", "") == self.wake_word.replace(" ", "")
        )
        if wake_event or wake_command:
            accepted = self.runtime.wake_detected(self.wake_word)
            if not accepted:
                self.runtime_status(
                    "wake_ignored",
                    reason="runtime_not_idle",
                )
                return
            self.armed_until = time.monotonic() + self.follow_up_timeout
            self.runtime_status("wake_detected")
            self.status("wake_detected backend=drobotics")

    def on_asr(self, msg):
        text = (msg.data or "").strip()
        if not text:
            return
        now = time.monotonic()
        if now > self.armed_until:
            self.status("asr_ignored reason=not_woken")
            return
        normalized = "".join(text.split())
        wake = "".join(self.wake_word.split())
        if normalized.startswith(wake):
            text = normalized[len(wake):].strip("，。！？,.!?：:;； ")
            if not text:
                self.armed_until = now + self.follow_up_timeout
                return
        # suppress a duplicate result emitted twice for the same utterance
        if text == self.last_text and now - self.last_text_at < 1.0:
            return
        self.last_text = text
        self.last_text_at = now
        self.armed_until = now + self.follow_up_timeout
        try:
            self.runtime.utterance_final(text)
            self.runtime.continue_listening("drobotics_follow_up")
        except ValueError as exc:
            self.runtime_status("invalid_transition", error=str(exc))
        else:
            self.runtime_status("utterance_final")
        self.text_pub.publish(String(data=text))
        self.command_pub.publish(String(data=text))
        self.status("asr_accepted backend=drobotics")

    def on_llm_status(self, msg):
        text = spoken_status(msg.data)
        if text:
            self._mark_estimated_playback(text)
            self.tts_pub.publish(String(data=text))


def main(args=None):
    rclpy.init(args=args)
    node = DRoboticsVoiceSuiteBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
