"""Silero endpoints on CPU, independent of ASR and robot command routing."""
import numpy as np
import sherpa_onnx

class SpeechVAD:
    def __init__(self,model):
        config=sherpa_onnx.VadModelConfig()
        config.silero_vad.model=str(model)
        config.silero_vad.threshold=.5
        config.silero_vad.min_speech_duration=.2
        config.silero_vad.min_silence_duration=.5
        config.silero_vad.max_speech_duration=20.
        config.sample_rate=16000;config.num_threads=1
        self.window=config.silero_vad.window_size
        self.vad=sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=30)
        self.reset()

    def reset(self):
        self.vad.reset();self.pending=np.empty(0,dtype=np.float32)

    def feed(self,samples):
        self.pending=np.concatenate((self.pending,samples))
        while len(self.pending)>=self.window:
            self.vad.accept_waveform(self.pending[:self.window])
            self.pending=self.pending[self.window:]
            if not self.vad.empty():
                result=np.array(self.vad.front.samples,dtype=np.float32,copy=True)
                self.vad.pop()
                return result
        return None
