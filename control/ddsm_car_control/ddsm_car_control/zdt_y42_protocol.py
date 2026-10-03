import time
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional

import serial


MODBUS_READ_INPUT_REGISTERS = 0x04
MODBUS_WRITE_MULTIPLE_REGISTERS = 0x10
MODBUS_WRITE_SINGLE_REGISTER = 0x06

FREE_FRAME_TAIL = 0x6B


def extract_free_frame(
    buffer: bytes,
    response_len: int,
    expected_address: int,
    function_code: int,
) -> Optional[bytes]:
    if response_len <= 0 or len(buffer) < response_len:
        return None
    for start in range(len(buffer) - response_len + 1):
        candidate = buffer[start : start + response_len]
        if (
            candidate[0] == (expected_address & 0xFF)
            and candidate[1] == (function_code & 0xFF)
            and candidate[-1] == FREE_FRAME_TAIL
        ):
            return candidate
    return None


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc16_modbus(data: bytes) -> bytes:
    crc = crc16_modbus(data)
    return data + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def validate_crc16_modbus(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16_modbus(frame[:-2]) == int.from_bytes(frame[-2:], "little")


def _u16(value: int) -> bytes:
    value = int(value) & 0xFFFF
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def _u32(value: int) -> bytes:
    value = int(value) & 0xFFFFFFFF
    return bytes(
        [
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )


def _clamp_int(value: float, lower: int, upper: int) -> int:
    return min(max(int(round(value)), lower), upper)


def rpm_to_direction_and_magnitude(rpm: float, scale: float = 1.0, max_units: int = 3000) -> tuple[int, int]:
    direction = 0 if rpm >= 0.0 else 1
    magnitude = _clamp_int(abs(rpm) * scale, 0, max_units)
    return direction, magnitude


def build_modbus_read_registers(
    address: int,
    register_address: int,
    count: int,
    function_code: int = MODBUS_READ_INPUT_REGISTERS,
) -> bytes:
    payload = bytes([address & 0xFF, function_code & 0xFF]) + _u16(register_address) + _u16(count)
    return append_crc16_modbus(payload)


def build_modbus_write_multiple_registers(
    address: int,
    register_address: int,
    values: list[int],
) -> bytes:
    payload = (
        bytes([address & 0xFF, MODBUS_WRITE_MULTIPLE_REGISTERS])
        + _u16(register_address)
        + _u16(len(values))
        + bytes([len(values) * 2])
        + b"".join(_u16(value) for value in values)
    )
    return append_crc16_modbus(payload)


def build_modbus_write_single_register(address: int, register_address: int, value: int) -> bytes:
    payload = bytes([address & 0xFF, MODBUS_WRITE_SINGLE_REGISTER]) + _u16(register_address) + _u16(value)
    return append_crc16_modbus(payload)


def build_modbus_emm_speed_frame(
    address: int,
    rpm: float,
    acceleration: int = 10,
    sync: bool = True,
) -> bytes:
    direction, speed = rpm_to_direction_and_magnitude(rpm, scale=1.0, max_units=3000)
    acc = _clamp_int(acceleration, 0, 255)
    values = [
        (direction << 8) | acc,
        speed,
        ((1 if sync else 0) << 8),
    ]
    return build_modbus_write_multiple_registers(address, 0x00F6, values)


def build_free_emm_speed_frame(
    address: int,
    rpm: float,
    acceleration: int = 10,
    sync: bool = True,
) -> bytes:
    direction, speed = rpm_to_direction_and_magnitude(rpm, scale=1.0, max_units=3000)
    return (
        bytes([address & 0xFF, 0xF6, direction])
        + _u16(speed)
        + bytes([_clamp_int(acceleration, 0, 255), 1 if sync else 0, FREE_FRAME_TAIL])
    )


def build_free_x_speed_frame(
    address: int,
    rpm: float,
    acceleration_rpm_s: int = 1000,
    sync: bool = True,
) -> bytes:
    direction, speed = rpm_to_direction_and_magnitude(rpm, scale=10.0, max_units=30000)
    return (
        bytes([address & 0xFF, 0xF6, direction])
        + _u16(_clamp_int(acceleration_rpm_s, 0, 65535))
        + _u16(speed)
        + bytes([1 if sync else 0, FREE_FRAME_TAIL])
    )


def build_modbus_sync_frame(address: int = 0) -> bytes:
    return build_modbus_write_single_register(address, 0x00FF, 0x6600)


def build_free_sync_frame(address: int = 0) -> bytes:
    return bytes([address & 0xFF, 0xFF, 0x66, FREE_FRAME_TAIL])


def build_modbus_stop_frame(address: int, sync: bool = False) -> bytes:
    return build_modbus_write_single_register(address, 0x00FE, 0x9800 | (1 if sync else 0))


def build_free_stop_frame(address: int, sync: bool = False) -> bytes:
    return bytes([address & 0xFF, 0xFE, 0x98, 1 if sync else 0, FREE_FRAME_TAIL])


def decode_modbus_registers_response(frame: bytes, expected_address: Optional[int] = None) -> bytes:
    if not validate_crc16_modbus(frame):
        raise ValueError("bad modbus crc")
    if expected_address is not None and frame[0] != expected_address:
        raise ValueError(f"unexpected address {frame[0]}")
    if frame[1] & 0x80:
        raise ValueError(f"modbus exception 0x{frame[2]:02x}")
    byte_count = frame[2]
    if len(frame) != 3 + byte_count + 2:
        raise ValueError("mis-sized modbus response")
    return frame[3 : 3 + byte_count]


def decode_signed_position_degrees(data: bytes, firmware: str = "emm") -> float:
    if len(data) != 6:
        raise ValueError("position response must contain 6 data bytes")
    sign = int.from_bytes(data[0:2], "big")
    raw = int.from_bytes(data[2:6], "big")
    value = -raw if sign else raw
    if firmware.lower() == "x":
        return value / 10.0
    return value * 360.0 / 65536.0


def decode_signed_speed_rpm(data: bytes, firmware: str = "emm") -> float:
    if len(data) != 4:
        raise ValueError("speed response must contain 4 data bytes")
    sign = int.from_bytes(data[0:2], "big")
    raw = int.from_bytes(data[2:4], "big")
    value = -raw if sign else raw
    if firmware.lower() == "x":
        return value / 10.0
    return float(value)


def decode_free_position_degrees(frame: bytes, expected_address: Optional[int] = None, firmware: str = "emm") -> float:
    if len(frame) != 8 or frame[-1] != FREE_FRAME_TAIL:
        raise ValueError("bad free-protocol position frame")
    if expected_address is not None and frame[0] != expected_address:
        raise ValueError(f"unexpected address {frame[0]}")
    if frame[1] != 0x36:
        raise ValueError(f"unexpected free-protocol function 0x{frame[1]:02x}")
    sign = frame[2]
    raw = int.from_bytes(frame[3:7], "big")
    value = -raw if sign else raw
    if firmware.lower() == "x":
        return value / 10.0
    return value * 360.0 / 65536.0


def decode_free_speed_rpm(frame: bytes, expected_address: Optional[int] = None, firmware: str = "emm") -> float:
    if frame[-1] != FREE_FRAME_TAIL:
        raise ValueError("bad free-protocol speed frame")
    if expected_address is not None and frame[0] != expected_address:
        raise ValueError(f"unexpected address {frame[0]}")
    if frame[1] != 0x35:
        raise ValueError(f"unexpected free-protocol function 0x{frame[1]:02x}")
    if len(frame) == 6:
        sign = frame[2]
        raw = int.from_bytes(frame[3:5], "big")
    elif len(frame) == 5:
        sign = 0
        raw = int.from_bytes(frame[2:4], "big")
    else:
        raise ValueError("bad free-protocol speed frame length")
    value = -raw if sign else raw
    if firmware.lower() == "x":
        return value / 10.0
    return float(value)


@dataclass
class ZDTMotorFeedback:
    address: int
    position_degrees: Optional[float] = None
    speed_rpm: Optional[float] = None
    valid: bool = False
    error: str = ""
    stamp: float = 0.0


class ZDTY42SerialBus:
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 0.03,
        protocol: str = "modbus",
        firmware: str = "emm",
        modbus_ack_writes: bool = True,
        free_ack_writes: bool = True,
    ) -> None:
        self.port = port
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.protocol = protocol.lower()
        self.firmware = firmware.lower()
        self.modbus_ack_writes = bool(modbus_ack_writes)
        self.free_ack_writes = bool(free_ack_writes)
        self._lock = Lock()
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
        )
        time.sleep(min(max(self.timeout, 0.01), 0.05))
        self._serial.reset_input_buffer()

    def close(self) -> None:
        self._serial.close()

    def write(self, frame: bytes) -> None:
        with self._lock:
            self._serial.write(frame)
            self._serial.flush()

    def write_modbus_command(self, frame: bytes, response_len: int = 8) -> None:
        if not self.modbus_ack_writes:
            self.write(frame)
            return
        response = self.exchange(frame, response_len)
        if not validate_crc16_modbus(response):
            raise ValueError("bad modbus write response crc")
        if response[0] != frame[0] or response[1] != frame[1]:
            raise ValueError("unexpected modbus write response")

    def write_free_command(self, frame: bytes, response_len: int = 4) -> None:
        if not self.free_ack_writes:
            self.write(frame)
            return
        response = self.exchange(frame, response_len)
        # Y42 tools can be configured for None/Receive/Reached/Both acknowledgements.
        # Clear whatever short response is present, but do not block velocity control
        # if the drive's acknowledgement policy differs from the manual default.
        if len(response) == response_len and response[-1] == FREE_FRAME_TAIL:
            return

    def exchange(self, frame: bytes, response_len: int) -> bytes:
        with self._lock:
            self._serial.reset_input_buffer()
            self._serial.write(frame)
            self._serial.flush()
            return self._serial.read(response_len)

    def exchange_free_frame(self, frame: bytes, response_len: int, expected_address: int, function_code: int) -> bytes:
        deadline = time.monotonic() + max(self.timeout * 3.0, 0.05)
        buffer = bytearray()
        with self._lock:
            self._serial.reset_input_buffer()
            self._serial.write(frame)
            self._serial.flush()
            while time.monotonic() < deadline:
                waiting = self._serial.in_waiting
                chunk = self._serial.read(waiting if waiting > 0 else 1)
                if chunk:
                    buffer.extend(chunk)
                    candidate = extract_free_frame(
                        bytes(buffer),
                        response_len,
                        expected_address,
                        function_code,
                    )
                    if candidate is not None:
                        return candidate
                    if len(buffer) > response_len * 4:
                        del buffer[: -response_len]
                else:
                    time.sleep(0.001)
        return bytes(buffer[:response_len])

    def build_speed_frame(self, address: int, rpm: float, acceleration: int, sync: bool) -> bytes:
        if self.protocol == "free":
            if self.firmware == "x":
                return build_free_x_speed_frame(address, rpm, acceleration, sync=sync)
            return build_free_emm_speed_frame(address, rpm, acceleration, sync=sync)
        if self.firmware == "x":
            raise NotImplementedError("X firmware MODBUS speed frame needs on-hardware verification")
        return build_modbus_emm_speed_frame(address, rpm, acceleration, sync=sync)

    def set_speed(self, address: int, rpm: float, acceleration: int = 10, sync: bool = True) -> None:
        frame = self.build_speed_frame(address, rpm, acceleration, sync)
        if self.protocol == "modbus":
            self.write_modbus_command(frame)
            return
        self.write_free_command(frame)

    def trigger_sync(self) -> None:
        if self.protocol == "free":
            frame = build_free_sync_frame(0)
            if self.free_ack_writes:
                self.write_free_command(frame)
            else:
                self.write(frame)
        else:
            self.write(build_modbus_sync_frame(0))

    def stop_motor(self, address: int, sync: bool = False) -> None:
        if self.protocol == "free":
            self.write_free_command(build_free_stop_frame(address, sync=sync))
        else:
            self.write_modbus_command(build_modbus_stop_frame(address, sync=sync))

    def read_position_degrees(self, address: int) -> float:
        if self.protocol == "free":
            frame = self.exchange_free_frame(bytes([address & 0xFF, 0x36, FREE_FRAME_TAIL]), 8, address, 0x36)
            return decode_free_position_degrees(frame, address, self.firmware)

        register = 0x0046 if self.firmware == "emm" else 0x0036
        request = build_modbus_read_registers(address, register, 3)
        data = decode_modbus_registers_response(self.exchange(request, 11), address)
        return decode_signed_position_degrees(data, self.firmware)

    def read_speed_rpm(self, address: int) -> float:
        if self.protocol == "free":
            frame = self.exchange_free_frame(bytes([address & 0xFF, 0x35, FREE_FRAME_TAIL]), 6, address, 0x35)
            return decode_free_speed_rpm(frame, address, self.firmware)

        register = 0x0044 if self.firmware == "emm" else 0x0035
        request = build_modbus_read_registers(address, register, 2)
        data = decode_modbus_registers_response(self.exchange(request, 9), address)
        return decode_signed_speed_rpm(data, self.firmware)

    def read_feedback(self, address: int, read_speed: bool = True) -> ZDTMotorFeedback:
        last_error = ""
        for attempt in range(2):
            try:
                position = self.read_position_degrees(address)
                speed = self.read_speed_rpm(address) if read_speed else None
                return ZDTMotorFeedback(
                    address=address,
                    position_degrees=position,
                    speed_rpm=speed,
                    valid=True,
                    stamp=time.monotonic(),
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    time.sleep(0.001)
        return ZDTMotorFeedback(
            address=address,
            valid=False,
            error=last_error,
            stamp=time.monotonic(),
        )

    def set_speeds(self, rpm_by_address: Dict[int, float], acceleration: int = 10, sync: bool = True) -> None:
        for address in sorted(rpm_by_address):
            self.set_speed(address, rpm_by_address[address], acceleration=acceleration, sync=sync)
        if sync:
            self.trigger_sync()
