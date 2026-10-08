from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

from .audio_frontend import AudioFrontendPolicy


class VoiceState(str, Enum):
    STARTING = "starting"
    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


_ALLOWED = {
    VoiceState.STARTING: {VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.IDLE: {
        VoiceState.CONNECTING,
        VoiceState.LISTENING,
        VoiceState.SPEAKING,
        VoiceState.ERROR,
    },
    VoiceState.CONNECTING: {
        VoiceState.IDLE,
        VoiceState.LISTENING,
        VoiceState.ERROR,
    },
    VoiceState.LISTENING: {
        VoiceState.THINKING,
        VoiceState.SPEAKING,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.THINKING: {
        VoiceState.SPEAKING,
        VoiceState.LISTENING,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    # The important xiaozhi-style transition: speaking -> listening.
    VoiceState.SPEAKING: {
        VoiceState.LISTENING,
        VoiceState.IDLE,
        VoiceState.ERROR,
    },
    VoiceState.ERROR: {VoiceState.STARTING, VoiceState.IDLE},
}


@dataclass(frozen=True)
class Transition:
    old: VoiceState
    new: VoiceState
    event: str
    generation: int


class VoiceStateMachine:
    """Small strict state machine modeled after xiaozhi-esp32."""

    def __init__(self) -> None:
        self.state = VoiceState.STARTING
        self.generation = 0
        self.last_event = "created"
        self.history: Deque[Transition] = deque(maxlen=32)

    def can_transition(self, target: VoiceState) -> bool:
        target = VoiceState(target)
        return target == self.state or target in _ALLOWED[self.state]

    def transition(self, target: VoiceState, event: str) -> VoiceState:
        target = VoiceState(target)
        if target == self.state:
            self.last_event = str(event)
            return self.state
        if not self.can_transition(target):
            raise ValueError(
                f"invalid voice state transition {self.state.value} -> "
                f"{target.value} ({event})"
            )
        old = self.state
        self.state = target
        self.last_event = str(event)
        self.history.append(
            Transition(old=old, new=target, event=str(event), generation=self.generation)
        )
        return self.state


class VoiceRuntime:
    """Luka L4 conversation/session state independent from robot motion.

    This object has no ROS/Nav2/DDSM imports.  It only models interaction state
    and the acoustic policy required for safe barge-in.
    """

    def __init__(
        self,
        frontend: Optional[AudioFrontendPolicy] = None,
        continuous_dialogue: bool = False,
    ) -> None:
        self.frontend = frontend or AudioFrontendPolicy()
        self.machine = VoiceStateMachine()
        self.continuous_dialogue = bool(continuous_dialogue)
        self.session_active = False
        self.playback_kind = ""
        self.last_wake_word = ""

    @property
    def state(self) -> VoiceState:
        return self.machine.state

    @property
    def generation(self) -> int:
        return self.machine.generation

    def ready(self) -> VoiceState:
        return self.machine.transition(VoiceState.IDLE, "runtime_ready")

    def wake_detected(self, wake_word: str, during_playback: bool = False) -> bool:
        if during_playback:
            if self.state is not VoiceState.SPEAKING:
                return False
            if not self.frontend.acoustic_barge_in:
                return False
            self.machine.generation += 1
            self.session_active = True
            self.last_wake_word = str(wake_word)
            self.machine.transition(VoiceState.LISTENING, "barge_in:wake_word")
            return True

        if self.state not in {VoiceState.IDLE, VoiceState.LISTENING}:
            return False
        self.session_active = True
        self.last_wake_word = str(wake_word)
        self.machine.transition(VoiceState.LISTENING, "wake_word")
        return True

    def manual_listen(self, event: str = "manual_wake") -> VoiceState:
        if self.state is VoiceState.SPEAKING:
            self.machine.generation += 1
            self.machine.transition(VoiceState.LISTENING, "barge_in:" + event)
        elif self.state in {
            VoiceState.IDLE,
            VoiceState.LISTENING,
            VoiceState.THINKING,
        }:
            self.machine.transition(VoiceState.LISTENING, event)
        else:
            raise ValueError(f"cannot start listening from {self.state.value}")
        self.session_active = True
        return self.state

    def utterance_final(self, text: str = "") -> VoiceState:
        if self.state is not VoiceState.LISTENING:
            # Existing Luka routing can finish a command just after an audio
            # event resets capture state. Fail closed for truly unrelated
            # states, but tolerate an already-thinking duplicate notification.
            if self.state is VoiceState.THINKING:
                return self.state
            raise ValueError(f"utterance final while {self.state.value}")
        self.machine.generation += 1
        return self.machine.transition(
            VoiceState.THINKING,
            "utterance_final" + (":" + str(text)[:32] if text else ""),
        )

    def playback_started(self, kind: str = "response") -> VoiceState:
        kind = str(kind or "response")
        self.playback_kind = kind
        if self.state is VoiceState.SPEAKING:
            return self.state
        return self.machine.transition(VoiceState.SPEAKING, "playback_started:" + kind)

    def playback_drained(self, kind: str = "") -> VoiceState:
        kind = str(kind or self.playback_kind or "response")
        self.playback_kind = ""
        # Playback may have been killed by barge-in. In that case the runtime
        # is already LISTENING and the stale drain event must not undo it.
        if self.state is not VoiceState.SPEAKING:
            return self.state
        if kind == "wake_ack":
            self.session_active = True
            return self.machine.transition(VoiceState.LISTENING, "wake_ack_drained")
        if self.continuous_dialogue and self.session_active:
            return self.machine.transition(
                VoiceState.LISTENING, "response_drained:continue"
            )
        self.session_active = False
        return self.machine.transition(VoiceState.IDLE, "response_drained")

    def manual_barge_in(self, event: str = "manual_interrupt") -> bool:
        if self.state is not VoiceState.SPEAKING:
            return False
        self.machine.generation += 1
        self.session_active = True
        self.machine.transition(VoiceState.LISTENING, "barge_in:" + str(event))
        return True

    def continue_listening(self, event: str = "conversation_continue") -> VoiceState:
        if self.state is VoiceState.SPEAKING:
            raise ValueError("cannot continue listening while playback is active")
        if self.state is VoiceState.THINKING:
            self.machine.transition(VoiceState.LISTENING, event)
        elif self.state is VoiceState.IDLE:
            self.machine.transition(VoiceState.LISTENING, event)
        elif self.state is not VoiceState.LISTENING:
            raise ValueError(f"cannot continue listening from {self.state.value}")
        self.session_active = True
        return self.state

    def end_session(self, event: str = "session_end") -> VoiceState:
        self.session_active = False
        self.playback_kind = ""
        if self.state is VoiceState.STARTING:
            return self.state
        if self.state is VoiceState.ERROR:
            return self.machine.transition(VoiceState.IDLE, event)
        if self.state is not VoiceState.IDLE:
            return self.machine.transition(VoiceState.IDLE, event)
        self.machine.last_event = event
        return self.state

    def error(self, event: str) -> VoiceState:
        self.session_active = False
        self.playback_kind = ""
        return self.machine.transition(VoiceState.ERROR, "error:" + str(event))

    def snapshot(self) -> dict:
        return {
            "state": self.state.value,
            "generation": self.generation,
            "last_event": self.machine.last_event,
            "session_active": self.session_active,
            "playback_kind": self.playback_kind,
            "continuous_dialogue": self.continuous_dialogue,
            "last_wake_word": self.last_wake_word,
            "frontend": self.frontend.snapshot(),
        }
