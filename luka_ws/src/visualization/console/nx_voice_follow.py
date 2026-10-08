"""Voice-to-face target acquisition for the existing fail-closed follow controller.

Only the current utterance's speaker candidate may nominate a face profile.
The worker never publishes wheel commands: the dashboard's follow controller
remains the sole motion gate and checks depth, scans, and target continuity.
"""
import json
import math
import threading
import time
import urllib.error
import urllib.request


PEOPLE = 'http://127.0.0.1:8098/api/people/'
DASHBOARD = 'http://127.0.0.1:8503/api/follow/'


def request(url, body=None, timeout=2):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            message = json.load(exc).get('error', '接口拒绝请求')
        except (ValueError, OSError):
            message = '接口拒绝请求'
        raise ValueError(message) from exc


def speaker_id(speaker, captured_at, now=None):
    """A nominated ID, not biometric authorization or target selection."""
    now = time.time() if now is None else now
    if not isinstance(speaker, dict) or not isinstance(captured_at, (int, float)):
        return None
    if not 0 <= now - captured_at <= 15:
        return None
    score = speaker.get('similarity')
    duration = speaker.get('audio_s')
    threshold = (.85 if duration < 1 else .82) if isinstance(duration, (int, float)) and duration < 2 else .75
    if (speaker.get('state') != 'candidate' or type(score) not in (int, float)
            or not math.isfinite(score) or score < threshold):
        return None
    ident = speaker.get('profile_id')
    return ident if isinstance(ident, str) and ident else None


def matching_face(state, voice_id):
    """Require one fresh, unambiguous, directly matched face/body pair."""
    if (not isinstance(state, dict) or state.get('active') is not True
            or state.get('loading') or state.get('error')
            or state.get('enrollment', {}).get('active')):
        return None
    age = state.get('camera_age')
    if not isinstance(age, (int, float)) or not math.isfinite(age) or not 0 <= age <= .7:
        return None
    matches = []
    for row in state.get('tracks') or []:
        identity = row.get('identity') or {}
        if (row.get('visible') is True and not row.get('association_ambiguous')
                and row.get('observation_strength') in ('strong', 'strong_detection')
                and identity.get('state') == 'matched'
                and identity.get('voice_profile_id') == voice_id
                and identity.get('id')):
            matches.append((row['track_id'], identity['id']))
    return matches[0] if len(matches) == 1 else None


class VoiceFollowCoordinator:
    def __init__(self, say, status=lambda text: None, get=request,
                 clock=time.monotonic, sleep=time.sleep):
        self.say, self.status, self.get = say, status, get
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._generation = 0

    def cancel(self):
        with self._lock:
            self._generation += 1

    def current(self, generation):
        with self._lock:
            return generation == self._generation

    def start(self, future, captured_at):
        self.cancel()
        with self._lock:
            generation = self._generation
        threading.Thread(target=self._run, args=(generation, future, captured_at),
                         daemon=True).start()

    def _run(self, generation, future, captured_at):
        try:
            try:
                speaker = future.result(timeout=10) if future else None
            except Exception:
                speaker = None
            if not self.current(generation):
                return
            voice_id = speaker_id(speaker, captured_at)
            if not voice_id:
                self.say('这句太短或声纹不够清楚。请说：露卡，我是主人，请跟着我走。')
                return
            # A new voice request cannot keep driving toward an old selected
            # person while the camera is searching for the new speaker.
            self.get(DASHBOARD + 'stop', {})
            self.say('我先找你，认出本人后再跟随。')
            deadline = self.clock() + 20
            last_frame = None
            candidate = None
            consecutive = 0
            while self.clock() < deadline and self.current(generation):
                state = self.get(PEOPLE + 'follow-state')
                frame = state.get('frame_at')
                match = matching_face(state, voice_id)
                if match and frame != last_frame:
                    consecutive = consecutive + 1 if match == candidate else 1
                    candidate = match
                    if consecutive >= 2:
                        break
                elif frame != last_frame:
                    candidate, consecutive = None, 0
                last_frame = frame
                self.sleep(.25)
            else:
                if self.current(generation):
                    self.say('我还没在画面中确认你的脸，请站在镜头前并露出脸，再说跟我走。')
                return
            if not self.current(generation):
                return
            track_id, face_id = candidate
            self.get(PEOPLE + 'select', {'track_id': track_id})
            # Selection is valid only when the worker's own current face match
            # established this exact face profile. User-confirmed identity is
            # intentionally insufficient for voice initiated motion.
            target_deadline = self.clock() + 3
            while self.clock() < target_deadline and self.current(generation):
                state = self.get(PEOPLE + 'follow-state')
                target = state.get('target_session') or {}
                if (target.get('active') and target.get('visible')
                        and target.get('track_id') == track_id
                        and target.get('profile_id') == face_id
                        and target.get('face_verified') is True
                        and target.get('confirmation_source') == 'face_match'):
                    break
                self.sleep(.2)
            else:
                if self.current(generation):
                    self.say('已看到疑似目标，但人脸尚未核对稳定，小车保持停车。')
                return
            if not self.current(generation):
                return
            try:
                result = self.get(DASHBOARD + 'start', {})
                if self.current(generation) and result.get('ok'):
                    self.say('已经认出并锁定你，开始跟随。')
            except Exception as exc:
                if self.current(generation):
                    self.say('已锁定你，但暂时不能行驶：' + str(exc)[:55])
        except Exception as exc:
            if self.current(generation):
                self.status('voice_follow_error ' + str(exc)[:120])
                self.say('自动找人暂时不可用，小车保持停车。')
