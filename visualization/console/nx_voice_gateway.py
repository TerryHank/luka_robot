from nx_music_focus import pause as pause_music
"""NX voice adapter: queue manual wake on the audio thread."""
import threading
import time
import rclpy
import json
import urllib.request
import urllib.error
import numpy as np
from pathlib import Path
import wave
from std_msgs.msg import String
from nav_llm_agent.voice_gateway import VoiceGateway, clean_command, deduplicate_command
from nx_voice_commands import route, hold_level, correct_room_command, destination_intent
from nx_speech_vad import SpeechVAD
from nx_tts_pipeline import TTSPipelineMixin
from nx_object_announcer import ObjectAnnouncer
from nx_voiceprint import VoiceprintWorker
from nx_voice_follow import VoiceFollowCoordinator
from nx_xfm_doa import XfmDoaReader

class NXVoiceGateway(TTSPipelineMixin, VoiceGateway):
    def __init__(self):
        self._chat_spoken=[]
        self.manual_wake=threading.Event()
        self.manual_cancel=threading.Event()
        self.command_peak=0.0
        self.test_next=False;self.test_capture=False
        self.conversation_active=False
        self.conversation_timeout=12.0
        self.speech_vad=SpeechVAD('/home/sunrise/luka_ws/common/models/voice/vad/silero_vad.onnx')
        super().__init__()
        self.speaker_command_pub=self.create_publisher(String,'/llm_voice_command',10)
        self._speaker_future=None;self._speaker_at=0.0
        self.voiceprint=VoiceprintWorker(self)
        self.voice_follow=VoiceFollowCoordinator(self.say,self._status)
        self.doa=XfmDoaReader()
        self.doa.prime()
        self.doa_pub=self.create_publisher(String,'/voice/doa',10)
        self._voiceprint_audio=None
        self.object_announcer=ObjectAnnouncer(self)
        self._status('endpoint_ready engine=silero silence=0.5s cpu_threads=1')

    def _end_conversation(self, reason='conversation_timeout'):
        self.conversation_active=False
        super()._return_to_wake(reason)

    def _return_to_wake(self, reason):
        self._voiceprint_audio=None
        self._speaker_future=None
        self.test_capture=False
        # Keep a short, hands-free follow-up window after a valid command.
        # Explicit cancellation, timeout, and shutdown paths return to KWS.
        if getattr(self, 'conversation_active', False) and not (
            reason.startswith(('manual_listen_cancelled', 'conversation_timeout',
                               'command_timeout_no_complete_vad_segment',
                               'audio_error', 'recognition_error'))
        ):
            self.mode='command'
            self.last_partial=''; self.command_parts=[]
            self._reset_command_capture()
            self.command_deadline=time.monotonic()+self.conversation_timeout
            try:self.voice_runtime.continue_listening(reason)
            except ValueError as exc:self._runtime_status('invalid_transition',error=str(exc))
            else:self._runtime_status('conversation_listening',reason=reason)
            self._status('conversation_listening timeout=12s reason='+reason)
            return
        super()._return_to_wake(reason)

    def _capture_wake_direction(self):
        event=self.doa.capture_after_wake()
        if not event:
            self._status('xfm_doa no_fresh_board_event')
            return
        if event.get('error'):
            self._status('xfm_doa_unavailable '+event['error'][:140])
            return
        self.doa_pub.publish(String(data=json.dumps(event,ensure_ascii=False)))
        self._status('xfm_doa angle_deg={angle_deg} relative_angle_deg={relative_angle_deg} beam={beam} score={score}'.format(**event) if event.get('calibrated') else 'xfm_doa angle_deg={angle_deg} beam={beam} score={score}'.format(**event))

    def _reset_command_capture(self):
        self.command_peak=0.0
        super()._reset_command_capture()
        if getattr(self,'speech_vad',None):self.speech_vad.reset()

    def _publish_command(self,text):
        command=deduplicate_command(clean_command(text,self.wake_word))
        self._runtime_utterance_final(command)
        corrected=correct_room_command(command)
        if corrected!=command:self._status(f'room_correction raw={command} corrected={corrected}')
        command=corrected
        sample=getattr(self,'_voiceprint_audio',None);self._voiceprint_audio=None
        if sample is not None and route(command) not in (('stop',None),('patrol_stop',None),('follow_start',None),('follow_stop',None)):
            self.voiceprint.submit(sample,self.sample_rate)
            self._return_to_wake('voiceprint_sample_received')
            return
        if getattr(self,'test_capture',False):
            self.test_capture=False
            self.text_pub.publish(String(data=command))
            self._return_to_wake('test_recognized text='+command)
            self.say('测试识别为：'+command)
            return
        action=route(command)
        destinations=[]
        if action is None or action[0]=='navigate':
            candidate=destination_intent(command,[])
            if candidate is not None:
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8503/api/voice/destinations',timeout=2) as response:destinations=json.load(response)['destinations']
                    action=destination_intent(command,destinations)
                except Exception:action=('destination_error','暂时无法读取目的地，请检查小车服务后再试。')
        if action is None:
            speaker={'state':'unknown'}
            future=getattr(self,'_speaker_future',None)
            if future:
                try:speaker=future.result(timeout=1.5)
                except Exception:pass
            envelope={'text':command,'speaker':speaker,'captured_at':self._speaker_at}
            self.text_pub.publish(String(data=command))
            self.speaker_command_pub.publish(String(data=json.dumps(envelope,ensure_ascii=False)))
            self._return_to_wake('speaker_command_sent')
            return
        speaker_future=getattr(self,'_speaker_future',None)
        speaker_at=getattr(self,'_speaker_at',0.)
        self.text_pub.publish(String(data=command))
        self._return_to_wake('voice_action text='+command)
        kind,poi=action
        if kind=='follow_start':
            self.voice_follow.start(speaker_future,speaker_at)
            return
        if kind in ('follow_stop','stop'):
            self.voice_follow.cancel()
        if kind=='come_find_me':
            doa=self.doa.latest(max_age_s=20.0)
            if not doa:
                self.say('我没有取得刚才的声源方向。请面对我再喊一次露卡，然后说来找我。')
                return
            if not doa.get('calibrated'):
                self.say('我取得了声源方向，但车头方向还没有校准。请站在车头正前方喊一次露卡。')
                return
            self._status('come_find_me_direction angle_deg={angle_deg} relative_angle_deg={relative_angle_deg} age_s={age_s}'.format(**doa))
            self.say('我听到你在车头相对{}度方向。请保持原地，再喊一次露卡确认，我会按这个方向开始找你。'.format(round(doa['relative_angle_deg'])))
            return
        if kind=='conversation_end':
            self._end_conversation('conversation_ended_by_user')
            self.say('好，我先安静等你。')
            return
        if kind in ('destination_list','destination_error'):
            self.say(poi if kind=='destination_error' else ('可前往：'+'、'.join(dict.fromkeys(d['display_name'] for d in destinations)) if destinations else '当前没有已确认的目的地。'))
            return
        if kind=='object_where':
            def reply_location():
                try:self.say(self.object_announcer.answer(poi))
                except Exception as exc:
                    self._status('object_lookup_failed '+str(exc))
                    self.say('暂时读不到找物记录，请检查视觉服务。')
            threading.Thread(target=reply_location,daemon=True).start()
            return
        path={'stop':'/api/nav/stop','navigate':'/api/nav','patrol_start':'/api/patrol/start','patrol_stop':'/api/patrol/stop','find_object':'/api/patrol/find','object_bring':'/api/patrol/bring','follow_start':'/api/follow/start','follow_stop':'/api/follow/stop'}[kind]
        body={'id':poi} if kind=='navigate' else {'query':poi} if kind=='find_object' else {}
        if kind=='object_bring':body={'query':poi}
        started=time.monotonic()
        try:
            req=urllib.request.Request('http://127.0.0.1:8503'+path,
                data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=20) as response:
                result=json.load(response)
            if not result.get('ok'):raise ValueError('导航接口未确认')
            reply=result.get('message') or ('跟随已启动，我会保持距离。' if kind=='follow_start' else '跟随已停止。' if kind=='follow_stop' else '导航已停止。' if kind=='stop' else '已提交前往'+result['display_name']+'的导航。')
            self._status(f'voice_action_accepted kind={kind} seconds={time.monotonic()-started:.3f}')
            self.say(reply)
        except urllib.error.HTTPError as exc:
            raw=exc.read(2048).decode(errors='replace');self._status('voice_action_rejected '+raw)
            try:self.say(json.loads(raw).get('error','操作未能执行，请查看网页。')[:100])
            except ValueError:self.say('操作未能执行，请查看网页状态。')
        except Exception as exc:
            # A lost HTTP reply can occur after goal acceptance: never retry it.
            self._status('voice_action_unconfirmed '+str(exc))
            self.say('未能确认导航状态，请检查网页，必要时按手柄接管。')

    def _on_voice_control(self,msg):
        command=(msg.data or '').strip().lower()
        if command in ('wake','test_wake'):
            self.test_next=command=='test_wake'
            self.manual_wake.set()
            self._status('manual_wake_requested')
        elif command=='cancel_listen':
            self.manual_cancel.set()
        else:
            super()._on_voice_control(msg)

    def manual_control(self):
        if self.manual_cancel.is_set():
            self.manual_cancel.clear();self.manual_wake.clear()
            self.kws_stream=self.kws.create_stream()
            self._return_to_wake('manual_listen_cancelled')
            return True
        if self.manual_wake.is_set():
            self.manual_wake.clear()
            self.conversation_active=False
            self.test_capture=self.test_next;self.test_next=False
            self.kws_stream=self.kws.create_stream()
            pause_music()
            self.mode='command'
            self.command_deadline=time.monotonic()+self.command_timeout
            self.last_partial='';self.command_parts=[]
            self._reset_command_capture()
            try:self.voice_runtime.manual_listen('manual_wake')
            except ValueError as exc:self._runtime_status('invalid_transition',error=str(exc))
            else:self._runtime_status('manual_wake')
            self._status('manual_wake_detected; listening')
            self.conversation_active=True
            return True
        return False

    def _process_wake(self,samples):
        if not self.manual_control():
            previous=self.mode
            super()._process_wake(samples)
            if self.mode=='command':
                self.conversation_active=True
                pause_music()
                if previous!='command':
                    threading.Thread(target=self._capture_wake_direction,daemon=True).start()

    def _process_command(self,samples):
        if self.manual_control():return
        if getattr(self,'speech_vad',None):
            started=time.monotonic()
            segment=self.speech_vad.feed(samples)
            if not self.command_started and self.speech_vad.vad.is_speech_detected():
                self.command_started=True
                self._status('vad_speech_started')
            if segment is not None:
                self.command_audio=[segment];self.command_audio_samples=len(segment)
                self._status(f'vad_endpoint duration={len(segment)/self.sample_rate:.3f}s processing_ms={(time.monotonic()-started)*1000:.2f}')
                self._recognize_command();return
            if time.monotonic()>=self.command_deadline:
                self.test_capture=False
                self._end_conversation('conversation_timeout')
            return
        baseline=self.noise_floor
        if self.command_started:
            level=float(np.sqrt(np.mean(np.square(samples))+1e-12))
            self.command_peak=max(self.command_peak,level)
            self.noise_floor=hold_level(baseline,self.command_peak)/1.6
        try:super()._process_command(samples)
        finally:self.noise_floor=baseline

    def _recognize_command(self):
        self._speaker_future=None;self._speaker_at=time.time()
        if getattr(self,'voiceprint',None) and not getattr(self,'test_capture',False):
            try:
                audio=np.concatenate(self.command_audio).astype(np.float32,copy=True)
                if self.voiceprint.store.pending():self._voiceprint_audio=audio
                else:self._speaker_future=self.voiceprint.submit(audio,self.sample_rate,with_result=True)
            except Exception as exc:self._status('voiceprint_unavailable '+str(exc))
        if getattr(self,'test_capture',False):
            root=Path('/home/sunrise/luka_ws/e2e/voice_tests');root.mkdir(exist_ok=True)
            path=root/(time.strftime('%Y%m%d_%H%M%S')+'.wav')
            audio=np.concatenate(self.command_audio)
            with wave.open(str(path),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(self.sample_rate)
                f.writeframes(np.clip(audio*32767,-32768,32767).astype('<i2').tobytes())
            self._status('test_audio_saved '+str(path))
        super()._recognize_command()

    def _on_llm_status(self,msg):
        # The agent publishes memory routing diagnostics before each request.
        # The base gateway speaks unknown statuses verbatim; keep this internal
        # event out of TTS without filtering text inside actual speech replies.
        if (msg.data or '').strip().startswith(('memory_scope:', 'queued:', 'queued_expired:')):
            return
        if (msg.data or '').startswith('speech:'):
            # Navigation may finish several seconds after the original voice
            # command. Keep the hands-free follow-up window open so the user
            # can answer the spoken "接下来要我做什么？" directly.
            if getattr(self, 'conversation_active', False):
                self.mode = 'command'
                self.command_deadline = time.monotonic() + self.conversation_timeout
            super()._on_llm_status(msg)
            return
        if (msg.data or '').startswith('speech: 录像第') and '候选' in msg.data:
            return  # Dedicated result watcher announces the first hit once.
        if (msg.data or '').startswith('received:'):
            self._chat_spoken=[]
            return
        if (msg.data or '').startswith('answer_streamed['):
            return  # Already spoken sentence by sentence; retain final status for UI/logs.
        if (msg.data or '').startswith('chat_sentence: '):
            reply=msg.data.partition(': ')[2].strip()
            if reply and reply not in self._chat_spoken:
                self._chat_spoken.append(reply)
                self.say(reply)
            return
        if (msg.data or '').startswith('answer['):
            reply=msg.data.partition(']: ')[2].strip()
            if reply and reply not in self._chat_spoken and reply!=''.join(self._chat_spoken):
                self._chat_spoken.append(reply)
                self.say(reply)
            return
        if (msg.data or '').startswith('dry_run:'):
            self.say('这个说法或功能暂未开放。导航请说去厨房、去卧室或去浴室。')
            return
        super()._on_llm_status(msg)

def main():
    rclpy.init();node=NXVoiceGateway()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()

if __name__=='__main__':main()
