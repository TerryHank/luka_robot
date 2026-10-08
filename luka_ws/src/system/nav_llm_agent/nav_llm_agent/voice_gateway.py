#!/usr/bin/env python3

import glob
import os
import re
import signal
import queue
import subprocess
import threading
import time
from collections import deque, OrderedDict
from typing import Optional

import numpy as np
import rclpy
import sherpa_onnx
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from nx_tts_backend import create_tts, validate_speaker_id


TAG_RE = re.compile(r"<\|[^|]+\|>")


def first_file(pattern: str) -> str:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(pattern)
    return matches[0]


def clean_command(text: str, wake_word: str) -> str:
    command = "".join(text.strip().split())
    for prefix in (wake_word, "人工智障", "路卡", "陆卡", "卢卡"):
        if command.startswith(prefix):
            command = command[len(prefix):]
    return command.strip("，。！？,.!?：:;； ")


def command_needs_more(text: str) -> bool:
    """Return True for command prefixes that are unsafe to dispatch alone."""
    command = "".join(text.strip().split())
    return command in {
        "去", "到", "前往", "导航", "导航到", "带我去", "我要去", "请去",
    }


def deduplicate_command(text: str) -> str:
    """Collapse an exact duplicated phrase produced from an overlong utterance."""
    command = "".join(text.strip().split())
    if len(command) >= 4 and len(command) % 2 == 0:
        half = len(command) // 2
        if command[:half] == command[half:]:
            return command[:half]
    return command


def speech_segments(text: str, limit: int = 24):
    """Bound first-chunk latency while preserving punctuation and ordering."""
    parts = re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]*|[。！？!?；;\n]+", text)
    result = []
    for part in parts:
        while len(part) > limit:
            cut = max(part.rfind(mark, 12, limit) for mark in "，,、：: ")
            cut = cut + 1 if cut >= 0 else limit
            result.append(part[:cut])
            part = part[cut:]
        if part.strip():
            result.append(part)
    return result


def speech_pcm(samples, sample_rate, volume, max_gain, lead_seconds):
    samples = np.asarray(samples, dtype=np.float32)
    if not samples.size or sample_rate <= 0 or not np.isfinite(samples).all():
        raise ValueError("TTS generated invalid audio")
    peak = float(np.max(np.abs(samples)))
    if peak > 1e-4:
        samples = np.clip(samples * min(max_gain, 0.85 / peak), -0.95, 0.95)
    pcm = np.clip(samples * volume * 32767.0, -32768, 32767).astype("<i2").tobytes()
    # Keep the beginning intact while the output device/power amplifier settles.
    return bytes(int(sample_rate * max(0.0, min(0.5, lead_seconds))) * 2) + pcm


class VoiceGateway(Node):
    def __init__(self) -> None:
        super().__init__("voice_gateway")
        model_root = "/home/sunrise/luka_data/ml_models/common/voice"
        self.declare_parameter("audio_device", "plughw:5,0")
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("chunk_ms", 100)
        self.declare_parameter("wake_word", "露卡")
        self.declare_parameter("command_timeout", 10.0)
        self.declare_parameter("command_pre_roll", 0.6)
        self.declare_parameter("command_start_frames", 2)
        self.declare_parameter("command_end_silence", 0.8)
        self.declare_parameter("command_min_speech", 0.4)
        self.declare_parameter("command_min_utterance", 0.8)
        self.declare_parameter("command_noise_calibration", 0.3)
        # +6 dB over the former level improves far-field pickup while keeping
        # the USB microphone's noisy hardware AGC disabled.
        self.declare_parameter("mic_capture_level", 25)
        self.declare_parameter("kws_threshold", 0.08)
        self.declare_parameter("kws_score", 2.5)
        self.declare_parameter("num_threads", 2)
        self.declare_parameter("asr_num_threads", 4)
        self.declare_parameter("tts_enabled", True)
        self.declare_parameter("tts_engine", "vits")
        self.declare_parameter(
            "tts_model_dir", os.path.join(model_root, "vits-zh-hf-fanchen-C")
        )
        self.declare_parameter("speaker_device", "plughw:4,0")
        self.declare_parameter("wake_response", "在呢")
        self.declare_parameter("wake_echo_guard", 0.2)
        self.declare_parameter("tts_num_threads", 4)
        self.declare_parameter("tts_volume", 1.0)
        self.declare_parameter("tts_speed", 1.08)
        self.declare_parameter("tts_sid", 14)
        self.declare_parameter("tts_max_gain", 4.0)
        self.declare_parameter("tts_lead_silence", 0.2)
        # The speaker is close to the microphone.  Keep capture muted during
        # synthesis/playback and briefly afterwards so Luca never treats her
        # own voice as a new wake word or command.
        self.declare_parameter("tts_echo_guard", 0.7)
        self.declare_parameter("speak_llm_status", True)
        self.declare_parameter("llm_status_topic", "/llm_status")
        self.declare_parameter(
            "kws_model_dir",
            os.path.join(
                model_root,
                "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01-mobile",
            ),
        )
        self.declare_parameter(
            "sensevoice_model_dir",
            os.path.join(model_root, "sensevoice"),
        )
        self.declare_parameter("keywords_file", os.path.join(model_root, "keywords.txt"))

        self.audio_device = str(self.get_parameter("audio_device").value)
        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.chunk_samples = max(
            160, int(self.sample_rate * int(self.get_parameter("chunk_ms").value) / 1000)
        )
        self.wake_word = str(self.get_parameter("wake_word").value)
        self.command_timeout = float(self.get_parameter("command_timeout").value)
        self.chunk_seconds = self.chunk_samples / float(self.sample_rate)
        self.command_pre_roll = float(self.get_parameter("command_pre_roll").value)
        self.command_start_frames = int(self.get_parameter("command_start_frames").value)
        self.command_end_silence = float(
            self.get_parameter("command_end_silence").value
        )
        self.command_min_speech = float(
            self.get_parameter("command_min_speech").value
        )
        self.command_min_utterance = float(
            self.get_parameter("command_min_utterance").value
        )
        self.command_noise_calibration = float(
            self.get_parameter("command_noise_calibration").value
        )
        self.mic_capture_level = max(
            0, min(30, int(self.get_parameter("mic_capture_level").value))
        )
        self.stop_event = threading.Event()
        self.tts_playing = threading.Event()
        self._tts_guard_lock = threading.Lock()
        self._tts_resume_at = 0.0
        self.audio_process: Optional[subprocess.Popen] = None
        self.mixer_configured = False
        self.mode = "wake"
        self.command_deadline = 0.0
        self.last_partial = ""
        self.command_parts = []
        self.noise_floor = 0.002
        self._ambient_levels = deque(maxlen=50)
        self._reset_command_capture()

        status_qos = QoSProfile(depth=10)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        self.command_pub = self.create_publisher(String, "/llm_command", 10)
        self.text_pub = self.create_publisher(String, "/voice/recognized_text", 10)
        self.status_pub = self.create_publisher(String, "/voice/status", status_qos)
        self.create_subscription(String, "/voice/control", self._on_voice_control, 10)
        self._last_spoken_status = ""
        self._last_spoken_at = 0.0
        if bool(self.get_parameter("speak_llm_status").value):
            self.create_subscription(
                String,
                str(self.get_parameter("llm_status_topic").value),
                self._on_llm_status,
                10,
            )

        kws_dir = str(self.get_parameter("kws_model_dir").value)
        asr_dir = str(self.get_parameter("sensevoice_model_dir").value)
        threads = max(1, int(self.get_parameter("num_threads").value))
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=os.path.join(kws_dir, "tokens.txt"),
            encoder=first_file(os.path.join(kws_dir, "encoder*.int8.onnx")),
            decoder=first_file(os.path.join(kws_dir, "decoder*.onnx")),
            joiner=first_file(os.path.join(kws_dir, "joiner*.int8.onnx")),
            keywords_file=str(self.get_parameter("keywords_file").value),
            num_threads=threads,
            keywords_score=float(self.get_parameter("kws_score").value),
            max_active_paths=8,
            keywords_threshold=float(self.get_parameter("kws_threshold").value),
            provider="cpu",
        )
        self.kws_stream = self.kws.create_stream()
        self.asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            tokens=os.path.join(asr_dir, "tokens.txt"),
            model=os.path.join(asr_dir, "model.int8.onnx"),
            num_threads=max(1, int(self.get_parameter("asr_num_threads").value)),
            sample_rate=self.sample_rate,
            language="zh",
            use_itn=True,
            provider="cpu",
        )
        self.tts = None
        self.tts_engine = str(self.get_parameter("tts_engine").value).strip().lower()
        # Text only: permit a complete streamed answer to queue while speech
        # plays. Audio prefetch remains bounded separately to two segments.
        self.speak_queue = queue.Queue(maxsize=128)
        self.speaker_device = str(self.get_parameter("speaker_device").value)
        self.tts_volume = max(
            0.0, min(1.0, float(self.get_parameter("tts_volume").value))
        )
        self.tts_speed = max(
            0.85, min(1.50, float(self.get_parameter("tts_speed").value))
        )
        self.tts_sid = int(self.get_parameter("tts_sid").value)
        self.tts_max_gain = max(
            1.0, min(4.0, float(self.get_parameter("tts_max_gain").value))
        )
        self.tts_echo_guard = max(
            0.2, min(2.0, float(self.get_parameter("tts_echo_guard").value))
        )
        self.wake_response = str(self.get_parameter("wake_response").value)
        self.wake_echo_guard = max(0.1, min(0.5, float(self.get_parameter("wake_echo_guard").value)))
        self._wake_audio = None
        self._speech_cache = OrderedDict()
        self._speech_cache_bytes = 0
        if bool(self.get_parameter("tts_enabled").value):
            try:
                tts_dir = str(self.get_parameter("tts_model_dir").value)
                self.tts = create_tts(
                    self.tts_engine, tts_dir,
                    threads=int(self.get_parameter("tts_num_threads").value),
                )
                self.tts_sid = validate_speaker_id(self.tts, self.tts_sid)
                # Prepare the acknowledgement once, so wake-up does not wait
                # for speech inference before the user hears feedback.
                if self.wake_response:
                    self._wake_audio = self.tts.generate(
                        self.wake_response, sid=self.tts_sid, speed=self.tts_speed
                    )
                # Cache fixed navigation responses before accepting speech.
                # Never publish commands or play audio while warming the cache.
                for label in ("厨房", "卧室", "浴室"):
                    for phrase in (f"好，这就带你去{label}。", f"到{label}啦。",
                                   f"暂时到不了{label}，导航失败了。"):
                        for segment in speech_segments(phrase):
                            self._speech_audio(segment)
                for phrase in ("导航已取消。", "酒店任务已暂停", "酒店任务已恢复"):
                    self._speech_audio(phrase)
                self._status(f"tts_cache_ready entries={len(self._speech_cache)} lead_silence={self.get_parameter('tts_lead_silence').value}")
                self.speak_thread = threading.Thread(
                    target=self._speak_loop, daemon=True
                )
                self.speak_thread.start()
                self._status(
                    f"tts_ready device={self.speaker_device} engine={self.tts_engine} "
                    f"sid={self.tts_sid} speed={self.tts_speed:.2f}"
                )
            except Exception as exc:
                self.tts = None
                self._status(
                    f"tts_disabled engine={self.tts_engine} sid={self.tts_sid} "
                    f"speed={self.tts_speed:.2f} {exc}"
                )

        self.audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self.audio_thread.start()
        self._status(f"ready wake_word={self.wake_word} device={self.audio_device}")

    def _status(self, text: str) -> None:
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)
        self.get_logger().info(text)

    def _start_audio(self) -> subprocess.Popen:
        if not self.mixer_configured:
            match = re.match(r"(?:plug)?hw:(\d+),", self.audio_device)
            if match:
                card = match.group(1)
                results = [
                    subprocess.run(
                        ["amixer", "-c", card, "cset", "numid=7", "on"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False,
                    ),
                    subprocess.run(
                        [
                            "amixer", "-c", card, "cset", "numid=8",
                            str(self.mic_capture_level),
                        ],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False,
                    ),
                    # Do not loop the microphone into the speaker output.
                    subprocess.run(
                        ["amixer", "-c", card, "cset", "numid=3", "off"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        check=False,
                    ),
                ]
                self.mixer_configured = all(x.returncode == 0 for x in results)
                self._status(
                    "microphone_gain="
                    + (
                        f"{round(self.mic_capture_level / 30 * 100)}%"
                        if self.mixer_configured else "setup_failed"
                    )
                )
        command = [
            "arecord", "-q", "-D", self.audio_device, "-t", "raw",
            "-f", "S16_LE", "-r", str(self.sample_rate), "-c", "1",
        ]
        return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _reset_command_capture(self) -> None:
        self.command_audio = []
        self.command_audio_samples = 0
        self.command_preroll = []
        self.command_hot_frames = 0
        self.command_started = False
        self.command_speech_seconds = 0.0
        self.command_silence_seconds = 0.0
        self.command_elapsed = 0.0
        self.command_noise_levels = []

    def _return_to_wake(self, reason: str) -> None:
        self.mode = "wake"
        self.last_partial = ""
        self.command_parts = []
        self._reset_command_capture()
        self.kws_stream = self.kws.create_stream()
        self._status(reason)

    def _publish_command(self, text: str) -> None:
        command = clean_command(text, self.wake_word)
        deduplicated = deduplicate_command(command)
        if deduplicated != command:
            self._status(f"command_deduplicated raw={command} text={deduplicated}")
            command = deduplicated
        if not command:
            self._return_to_wake("command_empty_after_clean")
            return
        recognized = String()
        recognized.data = command
        self.text_pub.publish(recognized)
        self.command_pub.publish(recognized)
        self._return_to_wake(f"command_sent text={command}")

    def _process_wake(self, samples: np.ndarray) -> None:
        level = float(np.sqrt(np.mean(np.square(samples)) + 1e-12))
        # Estimate from quiet frames across the previous five seconds. The old
        # <0.010 cutoff froze the baseline in noisy rooms and prevented VAD
        # from ever detecting the end of a command. Playback frames are already
        # excluded by the audio loop; freeze this estimate while taking commands.
        self._ambient_levels.append(level)
        if len(self._ambient_levels) >= 10:
            self.noise_floor = max(1e-4, float(np.percentile(self._ambient_levels, 20)))
        self.kws_stream.accept_waveform(self.sample_rate, samples)
        while self.kws.is_ready(self.kws_stream):
            self.kws.decode_stream(self.kws_stream)
            result = self.kws.get_result(self.kws_stream)
            if result:
                self.kws.reset_stream(self.kws_stream)
                self.mode = "command"
                self.command_deadline = time.monotonic() + self.command_timeout
                self.last_partial = ""
                self.command_parts = []
                self._reset_command_capture()
                self._status(f"wake_detected word={result}; listening")
                self.say(self.wake_response)
                return

    def _process_command(self, samples: np.ndarray) -> None:
        level = float(np.sqrt(np.mean(np.square(samples)) + 1e-12))
        self.command_elapsed += self.chunk_seconds
        # Use ambient noise measured before wake-up. Immediate speech after
        # the keyword must not train the noise floor or be discarded.
        baseline = self.noise_floor
        start_threshold = max(0.003, baseline * 2.5)
        hold_threshold = max(0.0025, baseline * 1.6)

        if not self.command_started:
            self.command_preroll.append(samples.copy())
            keep = max(1, int(self.command_pre_roll / self.chunk_seconds))
            if len(self.command_preroll) > keep:
                self.command_preroll = self.command_preroll[-keep:]
            self.command_hot_frames = (
                self.command_hot_frames + 1 if level >= start_threshold else 0
            )
            if self.command_hot_frames >= self.command_start_frames:
                self.command_started = True
                self.command_audio = list(self.command_preroll)
                self.command_audio_samples = sum(len(x) for x in self.command_audio)
                self.command_speech_seconds = (
                    self.command_start_frames * self.chunk_seconds
                )
                self.command_silence_seconds = 0.0
                self._status(
                    f"command_speech_started level={level:.4f} "
                    f"noise={baseline:.4f} start={start_threshold:.4f}"
                )
        else:
            self.command_audio.append(samples.copy())
            self.command_audio_samples += len(samples)
            if level >= hold_threshold:
                self.command_speech_seconds += self.chunk_seconds
                self.command_silence_seconds = 0.0
            else:
                self.command_silence_seconds += self.chunk_seconds
            duration = self.command_audio_samples / float(self.sample_rate)
            enough = (
                self.command_speech_seconds >= self.command_min_speech
                and duration >= self.command_min_utterance
            )
            if enough and self.command_silence_seconds >= self.command_end_silence:
                self._recognize_command()
                return

        if time.monotonic() >= self.command_deadline:
            duration = self.command_audio_samples / float(self.sample_rate)
            if self.command_started and duration >= 0.5:
                self._recognize_command()
            else:
                self._return_to_wake("command_timeout")

    def _recognize_command(self) -> None:
        started_at = time.monotonic()
        audio = np.concatenate(self.command_audio).astype(np.float32, copy=False)
        self._status(f"recognizing duration={len(audio) / self.sample_rate:.1f}s")
        try:
            stream = self.asr.create_stream()
            stream.accept_waveform(self.sample_rate, audio)
            self.asr.decode_stream(stream)
            text = TAG_RE.sub("", stream.result.text or "").strip()
            self._status(f"asr_timing seconds={time.monotonic() - started_at:.3f}")
        except Exception as exc:
            self._return_to_wake(f"recognition_error {exc}")
            return
        if text:
            self._publish_command(text)
        else:
            self._return_to_wake("command_unrecognized")

    def say(self, text: str) -> None:
        if self.tts is None or not text:
            return
        try:
            self.speak_queue.put_nowait(text)
        except queue.Full:
            self.get_logger().warning("speak queue full; dropped: %s" % text[:24])

    def _capture_blocked_by_tts(self) -> bool:
        if self.tts_playing.is_set():
            return True
        with self._tts_guard_lock:
            return time.monotonic() < self._tts_resume_at

    def _speech_audio(self, text):
        key = (text, self.tts_sid, self.tts_speed)
        if key in self._speech_cache:
            self._speech_cache.move_to_end(key)
            return self._speech_cache[key], True
        audio = self.tts.generate(text, sid=self.tts_sid, speed=self.tts_speed)
        size = np.asarray(audio.samples, dtype=np.float32).nbytes
        if size <= 16 * 1024 * 1024:
            while self._speech_cache and (len(self._speech_cache) >= 64 or
                    self._speech_cache_bytes + size > 16 * 1024 * 1024):
                _, old = self._speech_cache.popitem(last=False)
                self._speech_cache_bytes -= np.asarray(old.samples, dtype=np.float32).nbytes
            self._speech_cache[key] = audio
            self._speech_cache_bytes += size
        return audio, False

    def _speak_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                text = self.speak_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            proc = None
            playback_started = False
            started_at = time.monotonic()
            try:
                is_wake_response = text == self.wake_response and self._wake_audio is not None
                segments = [text] if is_wake_response else speech_segments(text)
                for index, segment in enumerate(segments):
                    if self.stop_event.is_set():
                        break
                    synth_start = time.monotonic()
                    audio, cached = (self._wake_audio, True) if is_wake_response else self._speech_audio(segment)
                    synthesis_seconds = time.monotonic() - synth_start
                    lead = float(self.get_parameter("tts_lead_silence").value)
                    pcm = speech_pcm(audio.samples, int(audio.sample_rate), self.tts_volume,
                                     self.tts_max_gain, lead)
                    cmd = ["aplay", "-q", "-D", self.speaker_device,
                           "-f", "S16_LE", "-r", str(int(audio.sample_rate)), "-c", "1", "-"]
                    # Remain half-duplex across ALL segments and synthesis gaps.
                    self.tts_playing.set()
                    playback_started = True
                    self._status(f"tts_play_start segment={index+1}/{len(segments)} synthesis={synthesis_seconds:.3f} wait={time.monotonic()-started_at:.3f} cached={cached} lead={lead:.2f}")
                    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    proc.communicate(input=pcm, timeout=30)
                self._status(f"tts_timing total={time.monotonic() - started_at:.3f} segments={len(segments)}")
            except Exception as exc:
                if proc is not None and proc.poll() is None:
                    proc.kill()
                    proc.communicate()
                self.get_logger().warning("tts playback failed: %r" % (exc,))
            finally:
                # Keep discarding microphone samples after output stops; this
                # absorbs acoustic reverberation and the aplay tail.
                if playback_started:
                    with self._tts_guard_lock:
                        self._tts_resume_at = (
                            time.monotonic() + (
                                self.wake_echo_guard if text == self.wake_response
                                else self.tts_echo_guard
                            )
                        )
                    self.tts_playing.clear()

    def _on_llm_status(self, msg) -> None:
        text = (msg.data or "").strip()
        if not text or text.startswith(("received:", "routing:", "ready:", "direct_match:", "sending:", "submitted:")):
            return
        friendly = text
        if text.startswith("speech:"):
            friendly = text.partition(":")[2].strip()
        elif text.startswith("answer["):
            _, _, friendly = text.partition("]: ")
        elif text.startswith("direct_match: navigate "):
            friendly = "好哒！这就带你去" + text[len("direct_match: navigate "):]
        elif text.startswith("busy"):
            friendly = "稍等我一下，上一条还在处理呢。"
        elif text.startswith("llm_error"):
            friendly = "哎呀，我刚才没听明白，能再说一次吗？"
        friendly = friendly[:48]
        now = time.monotonic()
        if friendly == self._last_spoken_status and now - self._last_spoken_at < 5.0:
            return
        self._last_spoken_status = friendly
        self._last_spoken_at = now
        self.say(friendly)

    def _on_voice_control(self, msg: String) -> None:
        command = (msg.data or "").strip().lower()
        if command == "volume_up":
            self.tts_volume = min(1.0, self.tts_volume + 0.1)
        elif command == "volume_down":
            self.tts_volume = max(0.2, self.tts_volume - 0.1)
        else:
            return
        self._status(f"tts_volume={self.tts_volume:.1f}")

    def _audio_loop(self) -> None:
        byte_count = self.chunk_samples * 2
        was_blocked = False
        while not self.stop_event.is_set():
            try:
                self.audio_process = self._start_audio()
                assert self.audio_process.stdout is not None
                self._status("audio_capture_started")
                while not self.stop_event.is_set():
                    raw = self.audio_process.stdout.read(byte_count)
                    if len(raw) != byte_count:
                        raise RuntimeError("audio stream ended")
                    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                    if self._capture_blocked_by_tts():
                        was_blocked = True
                        # Discard in real time instead of letting buffered TTS
                        # audio be decoded as a user utterance.  If we were
                        # waiting for a command after the wake response, begin
                        # a fresh capture window once playback has ended.
                        if self.mode == "command":
                            self._reset_command_capture()
                            self.command_deadline = (
                                time.monotonic() + self.command_timeout
                            )
                        continue
                    if was_blocked:
                        self.kws_stream = self.kws.create_stream()
                        self._reset_command_capture()
                        self.command_deadline = time.monotonic() + self.command_timeout
                        self._status(f"listening_resumed mode={self.mode}")
                        was_blocked = False
                    if self.mode == "wake":
                        self._process_wake(samples)
                    else:
                        self._process_command(samples)
            except Exception as exc:
                self._status(f"audio_error {exc}")
                time.sleep(1.0)
            finally:
                if self.audio_process is not None:
                    self.audio_process.terminate()
                    try:
                        self.audio_process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        self.audio_process.kill()
                    self.audio_process = None

    def destroy_node(self):
        self.stop_event.set()
        if self.audio_process is not None:
            self.audio_process.send_signal(signal.SIGTERM)
        if hasattr(self, "audio_thread"):
            self.audio_thread.join(timeout=2.0)
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceGateway()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
