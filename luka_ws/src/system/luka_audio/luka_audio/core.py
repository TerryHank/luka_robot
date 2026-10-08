import json
import struct
import time


def serial_frame(kind, message_id, payload):
    data = struct.pack('<BBBHH', 0xA5, 1, kind, len(payload), message_id) + payload
    return data + bytes([(-sum(data)) & 255])


class SerialFrames:
    """New M2 framing: resynchronise on corrupt input, bounded payload size."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 8:
            if self.buffer[:2] != b'\xa5\x01':
                del self.buffer[0]
                continue
            size, message_id = struct.unpack_from('<HH', self.buffer, 3)
            if size > 10232:
                del self.buffer[0]
                continue
            if len(self.buffer) < size + 8:
                break
            packet = bytes(self.buffer[:size + 8])
            if sum(packet) & 255:
                del self.buffer[0]
                continue
            del self.buffer[:size + 8]
            frames.append((packet[2], message_id, packet[7:-1]))
        return frames


class WakeEvents:
    def __init__(self):
        self.last = None

    def accept(self, identity, event, prime=False):
        if prime or identity == self.last:
            self.last = identity
            return None
        self.last = identity
        event = dict(event)
        event['observed_at'] = time.time()
        return event


class BackendRouter:
    """No reachability probe is treated as proof of AIUI authentication.

    Only confirmed loss of internet permits a local speech backend. AIUI auth,
    capability and service errors while online are reported, never hidden locally.
    """
    def __init__(self, aiui, rdk, configured, network):
        self.aiui, self.rdk = aiui, rdk
        self.configured, self.network = configured, network
        self.status = 'unverified' if configured() else 'unconfigured'

    def run(self, operation, payload):
        state = self.network()
        if state == 'offline':
            return 'rdk', self.rdk(operation, payload)
        if state != 'online':
            raise RuntimeError('internet state is not confirmed')
        if not self.configured():
            raise RuntimeError('AIUI cloud credentials are not configured')
        if state == 'online':
            try:
                result = self.aiui(operation, payload)
                self.status = 'healthy'
                return 'aiui', result
            except InterruptedError:
                raise
            except (RuntimeError, TimeoutError, OSError) as exc:
                self.status = 'failed:' + type(exc).__name__
                if self.network() == 'offline':
                    return 'rdk', self.rdk(operation, payload)
                raise


class BackendError(RuntimeError):
    def __init__(self, result):
        self.error_code = result.get('error_code') if type(result.get('error_code')) is int else 0
        self.error_scope = result.get('error_scope') if result.get('error_scope') in ('nlp', 'other') else ''
        self.timed_out = result.get('timed_out') is True
        super().__init__('speech backend failed: code ' + str(self.error_code))


def parse_result(stdout):
    # Native SDKs may write diagnostic lines. Only accept our final JSON object.
    for line in reversed(stdout.splitlines()):
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict):
            if result.get('ok') is True:
                return result
            if result.get('ok') is False:
                raise BackendError(result)
    raise RuntimeError('backend returned no successful result')
