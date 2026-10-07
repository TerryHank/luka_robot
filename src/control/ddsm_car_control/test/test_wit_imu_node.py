import math
import struct

from ddsm_car_control.wit_imu_node import (
    DEFAULT_BAUD,
    WitNormalParser,
    build_modbus_read_request,
    crc16_modbus,
    euler_to_quaternion,
    parse_modbus_register_response,
)


def normal_frame(frame_type, values):
    payload = struct.pack("<hhhh", *values)
    frame = bytearray([0x55, frame_type])
    frame.extend(payload)
    frame.append(sum(frame[:10]) & 0xFF)
    return bytes(frame)


def modbus_response(slave_id, registers):
    payload = bytearray([slave_id, 0x03, len(registers) * 2])
    for value in registers:
        payload.extend(struct.pack(">H", value & 0xFFFF))
    crc = crc16_modbus(payload)
    payload.extend([crc & 0xFF, (crc >> 8) & 0xFF])
    return bytes(payload)


def test_wit_normal_parser_publishes_sample_on_angle_frame():
    parser = WitNormalParser()

    assert parser.feed(normal_frame(0x51, [2048, 0, 16384, 0])) is None
    assert parser.feed(normal_frame(0x52, [0, 0, 327, 0])) is None
    sample = parser.feed(normal_frame(0x53, [0, 0, 16384, 0]))

    assert sample is not None
    assert sample.acceleration[0] == 2048 / 32768.0 * 16 * 9.8
    assert sample.acceleration[2] == 16384 / 32768.0 * 16 * 9.8
    assert sample.angular_velocity[2] == 327 / 32768.0 * 2000 * math.pi / 180
    assert sample.angle_radians[2] == math.pi / 2
    assert sample.quaternion == euler_to_quaternion(0.0, 0.0, math.pi / 2)


def test_wit_normal_parser_ignores_bad_checksum():
    parser = WitNormalParser()
    frame = bytearray(normal_frame(0x53, [0, 0, 16384, 0]))
    frame[-1] ^= 0xFF

    assert parser.feed(bytes(frame)) is None


def test_modbus_request_and_response_parser():
    request = build_modbus_read_request(slave_id=0x50, start_register=0x34, count=12)
    assert request[:6] == bytes([0x50, 0x03, 0x00, 0x34, 0x00, 0x0C])
    assert crc16_modbus(request[:-2]) == request[-2] | (request[-1] << 8)

    registers = [2048, 0, 16384, 0, 0, 327, 1, 2, 3, 0, 0, 16384]
    sample = parse_modbus_register_response(modbus_response(0x50, registers), 0x50, 12)

    assert sample is not None
    assert sample.acceleration[0] == 2048 / 32768.0 * 16 * 9.8
    assert sample.angular_velocity[2] == 327 / 32768.0 * 2000 * math.pi / 180
    assert sample.magnetometer == [1, 2, 3]
    assert sample.angle_radians[2] == math.pi / 2


def test_hwt906_defaults_to_detected_921600_baud():
    launch_text = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("launch", "wit_imu.launch.py")
        .read_text(encoding="utf-8")
    )

    assert DEFAULT_BAUD == 921600
    assert 'default_value="921600"' in launch_text
