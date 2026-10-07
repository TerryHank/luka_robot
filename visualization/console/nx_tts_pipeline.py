from nx_music_focus import duck as music_duck, restore as music_restore
"""Bounded, ordered playback pipeline for local CPU speech synthesis."""
import queue
import re
import subprocess
import threading
import time


PHRASE_LIMIT = 24


def phrase_segments(text, limit=PHRASE_LIMIT):
    """Split text already received, keeping short complete clauses intact."""
    limit = int(limit)
    if limit < 1:
        raise ValueError('phrase limit must be positive')
    soft_limit = min(16, limit)
    result = []
    for part in re.findall(r'[^，,。！？!?；;\n]+[，,。！？!?；;\n]*|[，,。！？!?；;\n]+', text):
        while len(part) > limit:
            # A comma/sentence clause of up to 24 characters is already
            # available, so do not turn its last word into a separate utterance.
            # For longer clauses prefer nearby natural boundaries over a hard
            # cut, without waiting for any further LLM tokens.
            boundaries = [
                index + 1 for index, char in enumerate(part[:limit])
                if (char.isspace() or char in '、：:')
                and index + 1 >= min(12, soft_limit)
                and len(part) - index - 1 >= 4
            ]
            cut = min(boundaries, key=lambda pos: (abs(pos-soft_limit), -pos)) if boundaries else soft_limit
            result.append(part[:cut])
            part = part[cut:]
        if part:
            result.append(part)
    return result


class TTSPipelineMixin:
    def _capture_blocked_by_tts(self):
        runtime=getattr(self,'voice_runtime',None)
        if runtime is not None and runtime.frontend.capture_during_playback:
            return False
        busy=getattr(self, '_tts_synth_busy', None)
        ready=getattr(self, '_tts_ready', None)
        return ((busy is not None and busy.is_set()) or
                (ready is not None and not ready.empty()) or
                not self.speak_queue.empty() or super()._capture_blocked_by_tts())

    def _interrupt_tts(self, reason):
        ready=getattr(self,'_tts_ready',None)
        dropped=0
        if ready is not None:
            while True:
                try:ready.get_nowait();dropped+=1
                except queue.Empty:break
        generation=super()._interrupt_tts(reason)
        self._status(f'tts_ready_cancelled generation={generation} dropped_ready={dropped}')
        return generation

    def _speak_loop(self):
        from nav_llm_agent.voice_gateway import speech_pcm
        self._tts_ready=queue.Queue(maxsize=2)
        self._tts_synth_busy=threading.Event()
        player=threading.Thread(target=self._play_ready_audio,daemon=True)
        player.start()
        self._status(f'tts_pipeline_ready prefetch=2 phrase_limit={PHRASE_LIMIT}')
        while not self.stop_event.is_set():
            try: text=self.speak_queue.get(timeout=.2)
            except queue.Empty: continue
            self._tts_synth_busy.set()
            started=time.monotonic()
            with self._tts_generation_lock:generation=self._tts_generation
            try:
                wake=text==self.wake_response and self._wake_audio is not None
                # Preserve cached acknowledgements, including navigation phrases.
                cached_whole=(text,self.tts_sid,self.tts_speed) in self._speech_cache
                segments=[text] if wake or cached_whole else phrase_segments(text)
                for index,segment in enumerate(segments):
                    if self.stop_event.is_set():break
                    with self._tts_generation_lock:
                        if generation!=self._tts_generation:break
                    synth_start=time.monotonic()
                    audio,cached=(self._wake_audio,True) if wake else self._speech_audio(segment)
                    synthesis=time.monotonic()-synth_start
                    lead=float(self.get_parameter('tts_lead_silence').value) if index==0 else 0.0
                    pcm=speech_pcm(audio.samples,int(audio.sample_rate),self.tts_volume,self.tts_max_gain,lead)
                    item=(pcm,int(audio.sample_rate),started,synthesis,cached,wake,index+1,len(segments),generation)
                    while not self.stop_event.is_set():
                        with self._tts_generation_lock:
                            if generation!=self._tts_generation:break
                        try:self._tts_ready.put(item,timeout=.2);break
                        except queue.Full:continue
            except Exception as exc:
                self.get_logger().warning('tts synthesis failed: %r' % (exc,))
            finally:self._tts_synth_busy.clear()
        player.join(timeout=2)

    def _play_ready_audio(self):
        while not self.stop_event.is_set():
            try:item=self._tts_ready.get(timeout=.2)
            except queue.Empty:continue
            pcm,rate,started,synthesis,cached,wake,index,count,generation=item
            with self._tts_generation_lock:
                if generation!=self._tts_generation:continue
            proc=None
            kind='wake_ack' if wake else 'response'
            music_volume=music_duck()
            self.tts_playing.set()
            if index==1:
                try:self.voice_runtime.playback_started(kind)
                except ValueError as exc:self._runtime_status('invalid_transition',error=str(exc))
                else:self._runtime_status('playback_started',kind=kind,generation=generation)
            try:
                self._status(f'tts_play_start pipeline=1 segment={index}/{count} synthesis={synthesis:.3f} wait={time.monotonic()-started:.3f} cached={cached}')
                proc=subprocess.Popen(['aplay','-q','-D',self.speaker_device,'-f','S16_LE','-r',str(rate),'-c','1','-'],stdin=subprocess.PIPE)
                with self._playback_lock:self._playback_proc=proc
                proc.communicate(input=pcm,timeout=30)
                if proc.returncode:raise RuntimeError(f'aplay exit={proc.returncode}')
                self._status(f'tts_segment_done segment={index}/{count} elapsed={time.monotonic()-started:.3f}')
            except Exception as exc:
                if proc is not None and proc.poll() is None:
                    proc.kill();proc.communicate()
                self.get_logger().warning('tts playback failed: %r' % (exc,))
            finally:
                music_restore(music_volume)
                with self._playback_lock:
                    if self._playback_proc is proc:self._playback_proc=None
                with self._tts_guard_lock:
                    self._tts_resume_at=time.monotonic()+(self.wake_echo_guard if wake else self.tts_echo_guard)
                self.tts_playing.clear()
                if index==count:
                    with self._tts_generation_lock:current_generation=self._tts_generation
                    if generation==current_generation:
                        state=self.voice_runtime.playback_drained(kind)
                        self._runtime_status('playback_drained',kind=kind,generation=generation)
                        if (kind=='response' and state.value=='listening' and
                                self.voice_runtime.continuous_dialogue):
                            self._arm_command_capture('continuous_dialogue')
                    else:
                        self._runtime_status('stale_playback_drained',
                            kind=kind,generation=generation,
                            current_generation=current_generation)
