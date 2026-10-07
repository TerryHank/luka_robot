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

class NXVoiceGateway(TTSPipelineMixin, VoiceGateway):
    def __init__(self):
        self._chat_spoken=[]
        self.manual_wake=threading.Event()
        self.manual_cancel=threading.Event()
        self.command_peak=0.0
        self.test_next=False;self.test_capture=False
        self.speech_vad=SpeechVAD('/home/sunrise/luka_ws/common/models/voice/vad/silero_vad.onnx')
        super().__init__()
        self.object_announcer=ObjectAnnouncer(self)
        self._status('endpoint_ready engine=silero silence=0.5s cpu_threads=1')

    def _reset_command_capture(self):
        self.command_peak=0.0
        super()._reset_command_capture()
        if getattr(self,'speech_vad',None):self.speech_vad.reset()

    def _return_to_wake(self,reason):
        self.test_capture=False
        super()._return_to_wake(reason)

    def _publish_command(self,text):
        command=deduplicate_command(clean_command(text,self.wake_word))
        corrected=correct_room_command(command)
        if corrected!=command:self._status(f'room_correction raw={command} corrected={corrected}')
        command=corrected
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
            return super()._publish_command(text)
        self.text_pub.publish(String(data=command))
        self._return_to_wake('voice_action text='+command)
        kind,poi=action
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
        if kind=='object_bring':
            try:job=self.object_announcer.bring_job(poi)
            except ValueError as exc:self.say(str(exc));return
            except Exception:
                self.say('暂时读不到找物记录，请检查视觉服务后再试。');return
        path={'stop':'/api/nav/stop','navigate':'/api/nav','patrol_start':'/api/patrol/start','patrol_stop':'/api/patrol/stop','find_object':'/api/patrol/find','object_bring':'/api/patrol/bring'}[kind]
        body={'id':poi} if kind=='navigate' else {'query':poi} if kind=='find_object' else {}
        if kind=='object_bring':body={'job_id':job['id'],'session':job['session'],'query':job['query']}
        started=time.monotonic()
        try:
            req=urllib.request.Request('http://127.0.0.1:8503'+path,
                data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=20) as response:
                result=json.load(response)
            if not result.get('ok'):raise ValueError('导航接口未确认')
            reply=result.get('message') or ('导航已停止。' if kind=='stop' else '已提交前往'+result['display_name']+'的导航。')
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
            self.test_capture=self.test_next;self.test_next=False
            self.kws_stream=self.kws.create_stream()
            self.mode='command'
            self.command_deadline=time.monotonic()+self.command_timeout
            self.last_partial='';self.command_parts=[]
            self._reset_command_capture()
            self._status('manual_wake_detected; listening')
            self.say(self.wake_response)
            return True
        return False

    def _process_wake(self,samples):
        if not self.manual_control():super()._process_wake(samples)

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
                self._return_to_wake('command_timeout_no_complete_vad_segment')
                self.say('没有听到完整的一句话，请再说一次。')
            return
        baseline=self.noise_floor
        if self.command_started:
            level=float(np.sqrt(np.mean(np.square(samples))+1e-12))
            self.command_peak=max(self.command_peak,level)
            self.noise_floor=hold_level(baseline,self.command_peak)/1.6
        try:super()._process_command(samples)
        finally:self.noise_floor=baseline

    def _recognize_command(self):
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
                self.say(reply[:120])
            return
        if (msg.data or '').startswith('answer['):
            reply=msg.data.partition(']: ')[2].strip()
            if reply and reply not in self._chat_spoken and reply!=''.join(self._chat_spoken):
                self._chat_spoken.append(reply)
                self.say(reply[:120])
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
