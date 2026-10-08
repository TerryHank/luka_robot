"""Read iFlytek XFM board wake-direction events through its USB ADB channel.

The microphone board owns its six-channel CAE processing.  Its public UAC endpoint is
processed mono, while the board demo log includes the wake event's angle/beam.  This
adapter only reads that event; it never changes board configuration or records audio.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

RUNTIME_PATH = Path("/home/sunrise/luka_data/runtime/audio/xfm_doa.json")
CALIBRATION_PATH = Path("/home/sunrise/luka_ws/src/common/runtime/xfm_doa_calibration.json")


class XfmDoaReader:
    def __init__(self, runtime_path: Path = RUNTIME_PATH, calibration_path: Path = CALIBRATION_PATH):
        self.runtime_path = runtime_path
        self.calibration_path = calibration_path
        self._lock = threading.Lock()
        self._last_start_ms = None
        self._latest = None
        self._available = None
        self._front_angle_deg = self._load_front_angle()

    def _load_front_angle(self):
        try:
            return float(json.loads(self.calibration_path.read_text(encoding="utf-8"))["front_angle_deg"]) % 360.0
        except Exception:
            return None

    def set_front_angle(self, angle_deg: float):
        self._front_angle_deg = float(angle_deg) % 360.0
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"front_angle_deg": self._front_angle_deg, "set_at": time.time(),
                   "source": "user_confirmed_car_front"}
        tmp = self.calibration_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.calibration_path)
        return payload

    def _calibrated(self, event):
        event = dict(event)
        event["front_angle_deg"] = self._front_angle_deg
        if self._front_angle_deg is not None:
            # 0 = car front, 90/270 retain the board's rotation convention.
            event["relative_angle_deg"] = round((event["angle_deg"] - self._front_angle_deg) % 360.0, 1)
            event["calibrated"] = True
        else:
            event["calibrated"] = False
        return event

    @staticmethod
    def _value(line: str, name: str, cast, default=None):
        # Board emits JSON as an escaped string in demo.log: \\"angle\\":66.0.
        # The enclosing JSON is not useful here; remove its escaping first.
        line = line.replace('\\', '')
        match = re.search(rf'"{re.escape(name)}"\s*:\s*("[^"]*"|[^,}}\s]+)', line)
        if not match:
            return default
        try:
            return cast(match.group(1).strip('"'))
        except (TypeError, ValueError):
            return default

    def _read_board_log(self):
        from adb_shell.transport.usb_transport import UsbTransport
        from adb_shell.adb_device import AdbDevice

        transport = next(UsbTransport.find_all_adb_devices(default_transport_timeout_s=3))
        device = AdbDevice(transport, default_transport_timeout_s=3)
        try:
            device.connect(rsa_keys=None, auth_timeout_s=3)
            text = device.shell("tail -n 100 /data/build/demo.log", timeout_s=4)
        finally:
            try:
                device.close()
            except Exception:
                pass

        event = None
        for line in reversed(text.splitlines()):
            if "aiui.uart:" not in line or "ivw" not in line or "angle" not in line:
                continue
            angle = self._value(line, "angle", float)
            start_ms = self._value(line, "start_ms", int)
            if angle is None or start_ms is None:
                continue
            event = self._calibrated({
                "angle_deg": round(angle % 360.0, 1),
                "beam": self._value(line, "beam", int),
                "physical_beam": self._value(line, "physical", int),
                "score": self._value(line, "score", float),
                "power": self._value(line, "power", float),
                "start_ms": start_ms,
                "keyword": self._value(line, "keyword", str),
                "source": "xfm_dp_board",
            })
            break
        return event

    def prime(self):
        """Establish a baseline so an old board wake is never reused."""
        try:
            event = self._read_board_log()
            self._available = True
            if event:
                self._last_start_ms = event["start_ms"]
            return event
        except Exception as exc:
            self._available = False
            return {"error": str(exc), "source": "xfm_dp_board"}

    def capture_after_wake(self, timeout_s: float = 1.4):
        """Wait briefly for the board's matching wake event and persist it."""
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                event = self._read_board_log()
                self._available = True
                if event and event["start_ms"] != self._last_start_ms:
                    with self._lock:
                        self._last_start_ms = event["start_ms"]
                        event["observed_at"] = time.time()
                        self._latest = event
                        self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
                        tmp = self.runtime_path.with_suffix(".tmp")
                        tmp.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
                        tmp.replace(self.runtime_path)
                    return event
            except Exception as exc:
                self._available = False
                if time.monotonic() >= deadline:
                    return {"error": str(exc), "source": "xfm_dp_board"}
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.16)

    def latest(self, max_age_s: float = 20.0):
        with self._lock:
            event = dict(self._latest) if self._latest else None
        if not event:
            try:
                event = json.loads(self.runtime_path.read_text(encoding="utf-8"))
            except Exception:
                return None
        age = time.time() - float(event.get("observed_at", 0))
        if age < 0 or age > max_age_s:
            return None
        event["age_s"] = round(age, 2)
        return event
