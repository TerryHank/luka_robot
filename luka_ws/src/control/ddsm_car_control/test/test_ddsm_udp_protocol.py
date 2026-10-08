import struct

import pytest

from ddsm_car_control.ddsm_udp_protocol import (
    COMMAND_MAGIC,
    DDSMUDPClient,
    ODOM_MAGIC,
    build_twist_packet,
    crc8_maxim,
    decode_odom_packet,
)


def test_build_twist_packet_uses_expected_binary_layout():
    packet = build_twist_packet(7, 0.25, 0.0, 0.5)

    assert len(packet) == 21
    assert packet[-1] == crc8_maxim(packet[:-1])

    magic, seq, _stamp_ms, vx, vy, wz = struct.unpack_from("<HHIfff", packet, 0)
    assert magic == COMMAND_MAGIC
    assert seq == 7
    assert vx == 0.25
    assert vy == 0.0
    assert wz == 0.5


def test_decode_odom_packet_reads_pose_twist_and_wheels():
    packet = bytearray()
    packet += struct.pack("<HHI", ODOM_MAGIC, 11, 1234)
    packet += struct.pack("<ffffff", 1.0, 2.0, 0.25, 0.3, 0.0, 0.1)
    packet += bytes([1])
    packet += struct.pack("<BBBhhHBH", 3, 1, 2, -4, 56, 12345, 0, 9)
    packet += bytes([crc8_maxim(packet)])

    odom = decode_odom_packet(bytes(packet))

    assert odom.seq == 11
    assert odom.stamp_ms == 1234
    assert odom.x == 1.0
    assert odom.y == 2.0
    assert odom.yaw == 0.25
    assert odom.vx == pytest.approx(0.3)
    assert odom.wz == pytest.approx(0.1)
    assert len(odom.wheels) == 1
    assert odom.wheels[0].wheel_id == 3
    assert odom.wheels[0].valid is True
    assert odom.wheels[0].speed_rpm == 56
    assert odom.wheels[0].age_ms == 9


def test_decode_odom_packet_reads_unwrapped_total_encoder_when_present():
    packet = bytearray()
    packet += struct.pack("<HHI", ODOM_MAGIC, 12, 5678)
    packet += struct.pack("<ffffff", 0.5, 0.0, 0.1, 0.2, 0.0, 0.01)
    packet += bytes([1])
    packet += struct.pack(
        "<BBBhhHiBH",
        1,
        1,
        2,
        -4,
        56,
        12345,
        -65540,
        0,
        9,
    )
    packet += bytes([crc8_maxim(packet)])

    odom = decode_odom_packet(bytes(packet))

    assert odom.wheels[0].position == 12345
    assert odom.wheels[0].total_encoder == -65540


def test_decode_odom_packet_reads_64_bit_total_encoder_when_present():
    packet = bytearray()
    packet += struct.pack("<HHI", ODOM_MAGIC, 13, 6789)
    packet += struct.pack("<ffffff", 0.5, 0.0, 0.1, 0.2, 0.0, 0.01)
    packet += bytes([1])
    packet += struct.pack(
        "<BBBhhHqBH",
        1,
        1,
        2,
        -4,
        56,
        12345,
        -4_294_967_300,
        0,
        9,
    )
    packet += bytes([crc8_maxim(packet)])

    odom = decode_odom_packet(bytes(packet))

    assert odom.wheels[0].position == 12345
    assert odom.wheels[0].total_encoder == -4_294_967_300


class FailingSendSocket:
    def sendto(self, _packet, _addr):
        raise OSError(101, "Network is unreachable")

    def close(self):
        pass


def test_send_twist_records_network_error_without_raising():
    client = DDSMUDPClient("192.168.3.139", command_port=9001, odom_port=0)
    try:
        client._sock.close()
        client._sock = FailingSendSocket()

        sent = client.send_twist(0.0, 0.0, 0.0)

        assert sent.seq == 0
        assert client.last_sent is sent
        assert client.last_send_error == "[Errno 101] Network is unreachable"
    finally:
        client.close()
