import json
import re
import time
from .core import SerialFrames, WakeEvents, serial_frame


class AdbWake:
    """Read existing XFM firmware events; never configure or flash the board."""
    def __init__(self):
        self.events = WakeEvents()
        self.connected = False

    def poll(self):
        from adb_shell.adb_device import AdbDeviceUsb
        device = AdbDeviceUsb(default_transport_timeout_s=2)
        try:
            device.connect(rsa_keys=None, auth_timeout_s=2, read_timeout_s=2)
            text = device.shell('tail -n 100 /data/build/demo.log', timeout_s=3, read_timeout_s=3)
        except Exception:
            self.connected = False
            raise
        finally:
            device.close()
        event = None
        for line in reversed(text.splitlines()):
            if 'aiui.uart:' not in line or 'ivw' not in line:
                continue
            line = line.replace('\\', '')
            def value(key, cast):
                match = re.search(r'"' + key + r'"\s*:\s*("[^"]*"|[^,}\s]+)', line)
                return cast(match[1].strip('"')) if match else None
            start, angle = value('start_ms', int), value('angle', float)
            if start is not None and angle is not None:
                event = {'start_ms': start, 'angle': angle, 'beam': value('beam', int),
                         'keyword': value('keyword', str), 'source': 'xfm_adb'}
                break
        result = self.events.accept(event['start_ms'], event, prime=not self.connected) if event else None
        self.connected = True
        return result


class SerialWake:
    """Open only the explicitly configured audio-device path."""
    def __init__(self, path):
        import serial
        self.port = serial.Serial(path, 115200, timeout=0.2)
        self.port.reset_input_buffer()
        self.frames = SerialFrames()
        self.events = WakeEvents()
        self.started_at = time.monotonic()

    def poll(self):
        event = None
        for kind, message_id, payload in self.frames.feed(self.port.read(4096)):
            if kind == 1 and payload == b'\xa5\0\0\0':
                self.port.write(serial_frame(255, message_id, payload))
            elif kind == 4:
                try:
                    data = json.loads(payload)
                    if data.get('type') != 'aiui_event':
                        continue
                    content = data['content']
                    if not 0 <= float(content['angle']) < 360:
                        continue
                    event = self.events.accept(message_id, dict(content, source='m2_serial'),
                                               prime=time.monotonic() - self.started_at < 1)
                except (ValueError, KeyError, TypeError):
                    continue
        return event

    def close(self):
        self.port.close()
