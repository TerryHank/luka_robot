import pytest

from ddsm_car_control.zdt_y42_protocol import (
    append_crc16_modbus,
    build_free_emm_speed_frame,
    build_free_x_speed_frame,
    build_modbus_emm_speed_frame,
    decode_signed_position_degrees,
    decode_signed_speed_rpm,
    extract_free_frame,
    validate_crc16_modbus,
)


def test_modbus_crc_matches_standard_reference_frame():
    frame = append_crc16_modbus(bytes.fromhex("01030000000a"))

    assert frame.hex() == "01030000000ac5cd"
    assert validate_crc16_modbus(frame)


def test_modbus_emm_speed_frame_matches_manual_layout():
    frame = build_modbus_emm_speed_frame(
        address=1,
        rpm=-1500,
        acceleration=10,
        sync=False,
    )

    assert frame[:-2].hex() == "011000f6000306010a05dc0000"
    assert validate_crc16_modbus(frame)


def test_free_emm_speed_frame_matches_manual_example_layout():
    frame = build_free_emm_speed_frame(
        address=1,
        rpm=-1500,
        acceleration=10,
        sync=False,
    )

    assert frame.hex() == "01f60105dc0a006b"


def test_free_x_speed_frame_uses_tenth_rpm_units_and_16bit_acceleration():
    frame = build_free_x_speed_frame(
        address=1,
        rpm=-2000,
        acceleration_rpm_s=1000,
        sync=False,
    )

    assert frame.hex() == "01f60103e84e20006b"


def test_decode_emm_position_register_units():
    data = bytes.fromhex("000000008000")

    assert decode_signed_position_degrees(data, firmware="emm") == pytest.approx(180.0)


def test_decode_emm_signed_speed_register_units():
    data = bytes.fromhex("00010064")

    assert decode_signed_speed_rpm(data, firmware="emm") == pytest.approx(-100.0)


def test_decode_x_firmware_uses_tenth_degree_and_tenth_rpm_units():
    position_data = bytes.fromhex("0000000004d2")
    speed_data = bytes.fromhex("00010064")

    assert decode_signed_position_degrees(position_data, firmware="x") == pytest.approx(123.4)
    assert decode_signed_speed_rpm(speed_data, firmware="x") == pytest.approx(-10.0)


def test_extract_free_position_frame_skips_stale_ack_byte():
    frame = extract_free_frame(
        bytes.fromhex("6b013600000447726b"),
        response_len=8,
        expected_address=1,
        function_code=0x36,
    )

    assert frame == bytes.fromhex("013600000447726b")


def test_extract_free_frame_returns_none_until_complete():
    frame = extract_free_frame(
        bytes.fromhex("01360000044772"),
        response_len=8,
        expected_address=1,
        function_code=0x36,
    )

    assert frame is None
