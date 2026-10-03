import socket
import struct
import time
from dataclasses import dataclass
from typing import List


COMMAND_MAGIC = 0xDDC2
ODOM_MAGIC = 0xDD52
COMMAND_PORT = 9001
ODOM_PORT = 9000


@dataclass
class WheelFeedback:
    wheel_id: int
    valid: bool
    mode: int
    torque: int
    speed_rpm: int
    position: int
    error: int
    age_ms: int
    total_encoder: int | None = None


@dataclass
class OdomFeedback:
    seq: int
    stamp_ms: int
    x: float
    y: float
    yaw: float
    vx: float
    vy: float
    wz: float
    wheels: List[WheelFeedback]


@dataclass
class SentTwistPacket:
    seq: int
    stamp_ms: int
    vx: float
    vy: float
    wz: float
    crc: int
    packet_hex: str
    packet_len: int


def crc8_maxim(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 0x01:
                crc = ((crc >> 1) ^ 0x8C) & 0xFF
            else:
                crc = (crc >> 1) & 0xFF
    return crc


def build_twist_packet(seq: int, vx: float, vy: float, wz: float) -> bytes:
    stamp_ms = int(time.monotonic() * 1000) & 0xFFFFFFFF
    payload = struct.pack(
        "<HHIfff",
        COMMAND_MAGIC,
        seq & 0xFFFF,
        stamp_ms,
        float(vx),
        float(vy),
        float(wz),
    )
    return payload + bytes([crc8_maxim(payload)])


def decode_odom_packet(packet: bytes) -> OdomFeedback:
    if len(packet) < 34:
        raise ValueError(f"short odom packet: {len(packet)} bytes")
    if crc8_maxim(packet[:-1]) != packet[-1]:
        raise ValueError("bad odom crc")

    magic, seq, stamp_ms = struct.unpack_from("<HHI", packet, 0)
    if magic != ODOM_MAGIC:
        raise ValueError(f"unexpected odom magic 0x{magic:04x}")

    x, y, yaw, vx, vy, wz = struct.unpack_from("<ffffff", packet, 8)
    count = packet[32]
    offset = 33
    wheel_payload_len = len(packet) - 1 - offset
    per_wheel_len = 0
    if count > 0:
        if wheel_payload_len % count != 0:
            raise ValueError("misaligned wheel feedback")
        per_wheel_len = wheel_payload_len // count
        if per_wheel_len not in (12, 16, 20):
            raise ValueError(f"unsupported wheel feedback size: {per_wheel_len} bytes")

    wheels = []
    for _ in range(count):
        if offset + per_wheel_len > len(packet) - 1:
            raise ValueError("truncated wheel feedback")
        if per_wheel_len == 20:
            wheel_id, valid, mode, torque, speed, pos, total_encoder, err, age = (
                struct.unpack_from("<BBBhhHqBH", packet, offset)
            )
        elif per_wheel_len == 16:
            wheel_id, valid, mode, torque, speed, pos, total_encoder, err, age = (
                struct.unpack_from("<BBBhhHiBH", packet, offset)
            )
        else:
            wheel_id, valid, mode, torque, speed, pos, err, age = struct.unpack_from(
                "<BBBhhHBH", packet, offset
            )
            total_encoder = None
        offset += per_wheel_len
        wheels.append(
            WheelFeedback(
                wheel_id=wheel_id,
                valid=bool(valid),
                mode=mode,
                torque=torque,
                speed_rpm=speed,
                position=pos,
                total_encoder=total_encoder,
                error=err,
                age_ms=age,
            )
        )

    return OdomFeedback(
        seq=seq,
        stamp_ms=stamp_ms,
        x=x,
        y=y,
        yaw=yaw,
        vx=vx,
        vy=vy,
        wz=wz,
        wheels=wheels,
    )


class DDSMUDPClient:
    def __init__(
        self,
        host: str,
        command_port: int = COMMAND_PORT,
        odom_port: int = ODOM_PORT,
    ) -> None:
        self.host = host
        self.command_port = command_port
        self.odom_port = odom_port
        self._seq = 0
        self.last_sent: SentTwistPacket | None = None
        self.last_send_error: str | None = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", odom_port))
        self._sock.setblocking(False)

    def close(self) -> None:
        self._sock.close()

    def send_twist(self, vx: float, vy: float, wz: float) -> SentTwistPacket:
        packet = build_twist_packet(self._seq, vx, vy, wz)
        _magic, seq, stamp_ms, sent_vx, sent_vy, sent_wz = struct.unpack_from(
            "<HHIfff", packet, 0
        )
        self.last_sent = SentTwistPacket(
            seq=seq,
            stamp_ms=stamp_ms,
            vx=sent_vx,
            vy=sent_vy,
            wz=sent_wz,
            crc=packet[-1],
            packet_hex=packet.hex(),
            packet_len=len(packet),
        )
        self._seq = (self._seq + 1) & 0xFFFF
        try:
            self._sock.sendto(packet, (self.host, self.command_port))
            self.last_send_error = None
        except OSError as exc:
            self.last_send_error = str(exc)
        return self.last_sent

    def stop(self, count: int = 8) -> None:
        for _ in range(count):
            self.send_twist(0.0, 0.0, 0.0)

    def recv_odom(self) -> OdomFeedback | None:
        try:
            packet, _addr = self._sock.recvfrom(2048)
        except BlockingIOError:
            return None
        return decode_odom_packet(packet)
