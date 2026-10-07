#!/usr/bin/env python3
from dataclasses import dataclass, field
import math
import struct
import time

import rclpy
from rclpy.node import Node
import serial
from sensor_msgs.msg import Imu, MagneticField


G = 9.8
DEFAULT_BAUD = 921600


@dataclass
class WitImuSample:
    acceleration: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    angular_velocity: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    magnetometer: list[int] = field(default_factory=lambda: [0, 0, 0])
    angle_radians: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    quaternion: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)


def euler_to_quaternion(roll: float, pitch: float, yaw: float):
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)

    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def checksum_ok(frame: bytes) -> bool:
    return len(frame) == 11 and (sum(frame[:10]) & 0xFF) == frame[10]


def signed_shorts_little_endian(payload: bytes):
    return struct.unpack("<hhhh", payload)


def decode_acceleration(values):
    return [value / 32768.0 * 16 * G for value in values[:3]]


def decode_angular_velocity(values):
    return [value / 32768.0 * 2000 * math.pi / 180 for value in values[:3]]


def decode_angle_radians(values):
    return [value / 32768.0 * math.pi for value in values[:3]]


class WitNormalParser:
    def __init__(self):
        self._buffer = bytearray()
        self._sample = WitImuSample()

    def feed(self, data: bytes):
        self._buffer.extend(data)
        latest = None
        while len(self._buffer) >= 11:
            if self._buffer[0] != 0x55:
                del self._buffer[0]
                continue
            frame = bytes(self._buffer[:11])
            del self._buffer[:11]
            latest = self._handle_frame(frame) or latest
        return latest

    def _handle_frame(self, frame: bytes):
        if not checksum_ok(frame):
            return None

        frame_type = frame[1]
        values = signed_shorts_little_endian(frame[2:10])
        if frame_type == 0x51:
            self._sample.acceleration = decode_acceleration(values)
        elif frame_type == 0x52:
            self._sample.angular_velocity = decode_angular_velocity(values)
        elif frame_type == 0x53:
            self._sample.angle_radians = decode_angle_radians(values)
            self._sample.quaternion = euler_to_quaternion(*self._sample.angle_radians)
            return WitImuSample(
                acceleration=list(self._sample.acceleration),
                angular_velocity=list(self._sample.angular_velocity),
                magnetometer=list(self._sample.magnetometer),
                angle_radians=list(self._sample.angle_radians),
                quaternion=self._sample.quaternion,
            )
        elif frame_type == 0x54:
            self._sample.magnetometer = list(values[:3])
        return None


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_modbus_read_request(slave_id=0x50, start_register=0x34, count=12):
    request = bytes(
        [
            slave_id,
            0x03,
            (start_register >> 8) & 0xFF,
            start_register & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ]
    )
    crc = crc16_modbus(request)
    return request + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def parse_modbus_register_response(data: bytes, slave_id=0x50, count=12):
    expected_length = 5 + count * 2
    if len(data) < expected_length:
        return None
    data = data[:expected_length]
    if data[0] != slave_id or data[1] != 0x03 or data[2] != count * 2:
        return None
    received_crc = data[-2] | (data[-1] << 8)
    if crc16_modbus(data[:-2]) != received_crc:
        return None

    raw_values = struct.unpack(">" + "H" * count, data[3 : 3 + count * 2])
    values = [value - 65536 if value > 32767 else value for value in raw_values]
    sample = WitImuSample()
    sample.acceleration = decode_acceleration(values[0:3])
    sample.angular_velocity = decode_angular_velocity(values[3:6])
    sample.magnetometer = values[6:9]
    sample.angle_radians = decode_angle_radians(values[9:12])
    sample.quaternion = euler_to_quaternion(*sample.angle_radians)
    return sample


class WitImuNode(Node):
    def __init__(self):
        super().__init__("wit_imu_node")
        self.declare_parameter("port", "/dev/ttyUSB0")
        self.declare_parameter("baud", DEFAULT_BAUD)
        self.declare_parameter("protocol", "normal")
        self.declare_parameter("frame_id", "base_link")
        self.declare_parameter("mounting_yaw", math.pi)
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("mag_topic", "/imu/mag")
        self.declare_parameter("poll_frequency", 100.0)
        self.declare_parameter("configure_output", True)
        self.declare_parameter("modbus_slave_id", 0x50)

        self.port = self.get_parameter("port").value
        self.baud = int(self.get_parameter("baud").value)
        self.protocol = str(self.get_parameter("protocol").value).lower()
        self.frame_id = self.get_parameter("frame_id").value
        self.mounting_yaw = float(self.get_parameter("mounting_yaw").value)
        self.configure_output = bool(self.get_parameter("configure_output").value)
        self.modbus_slave_id = int(self.get_parameter("modbus_slave_id").value)

        imu_topic = self.get_parameter("imu_topic").value
        mag_topic = self.get_parameter("mag_topic").value
        self.imu_pub = self.create_publisher(Imu, imu_topic, 10)
        self.mag_pub = self.create_publisher(MagneticField, mag_topic, 10)

        self.serial = None
        self.next_reconnect_time = 0.0
        self.parser = WitNormalParser()
        self.last_publish_time = time.monotonic()
        self.last_warn_time = 0.0

        self._connect_serial()

        poll_frequency = float(self.get_parameter("poll_frequency").value)
        self.timer = self.create_timer(1.0 / max(poll_frequency, 1.0), self._poll_once)
        self.get_logger().info(
            "WIT IMU node ready | port=%s baud=%d protocol=%s imu_topic=%s"
            % (self.port, self.baud, self.protocol, imu_topic)
        )

    def _disconnect_serial(self):
        if self.serial is not None:
            try:
                self.serial.close()
            except Exception:
                pass
        self.serial = None
        self.parser = WitNormalParser()
        self.next_reconnect_time = time.monotonic() + 2.0

    def _connect_serial(self):
        try:
            # Reopen the stable by-id path: USB device numbers can change.
            self.serial = serial.Serial(port=self.port, baudrate=self.baud, timeout=0.02)
            self.parser = WitNormalParser()
            if self.configure_output and self.protocol == "normal":
                self._configure_standard_output()
            self.last_publish_time = time.monotonic()
            self.get_logger().info("WIT IMU serial connected: %s" % self.port)
        except Exception as exc:
            self._disconnect_serial()
            self.get_logger().warn("WIT IMU reconnect failed; retry in 2s: %s" % exc)

    def _configure_standard_output(self):
        unlock = bytes([0xFF, 0xAA, 0x69, 0x88, 0xB5])
        set_rsw = bytes([0xFF, 0xAA, 0x02, 0x1F, 0x00])
        self.serial.write(unlock)
        time.sleep(0.1)
        self.serial.write(set_rsw)
        time.sleep(0.1)
        self.serial.reset_input_buffer()

    def _poll_once(self):
        if self.serial is None:
            if time.monotonic() >= self.next_reconnect_time:
                self._connect_serial()
            return
        try:
            if self.protocol == "modbus":
                sample = self._read_modbus_sample()
            else:
                sample = self._read_normal_sample()
            if sample:
                self._publish_sample(sample)
        except Exception as exc:
            self._disconnect_serial()
            self.get_logger().warn("WIT IMU disconnected; retry in 2s: %s" % exc)
            return

        now = time.monotonic()
        if now - self.last_publish_time > 5.0 and now - self.last_warn_time > 5.0:
            self.last_warn_time = now
            self.get_logger().warn(
                "No valid WIT IMU samples yet; check port, baud, protocol, wiring, and sensor output mode."
            )
            self._disconnect_serial()

    def _read_normal_sample(self):
        waiting = self.serial.in_waiting
        if waiting <= 0:
            return None
        return self.parser.feed(self.serial.read(waiting))

    def _read_modbus_sample(self):
        request = build_modbus_read_request(self.modbus_slave_id, 0x34, 12)
        self.serial.write(request)
        response = self.serial.read(5 + 12 * 2)
        return parse_modbus_register_response(response, self.modbus_slave_id, 12)

    def _publish_sample(self, sample: WitImuSample):
        stamp = self.get_clock().now().to_msg()
        roll, pitch, yaw = sample.angle_radians
        orientation = euler_to_quaternion(
            roll,
            pitch,
            yaw + self.mounting_yaw,
        )
        cos_yaw = math.cos(self.mounting_yaw)
        sin_yaw = math.sin(self.mounting_yaw)

        def rotate_xy(values):
            return (
                cos_yaw * values[0] - sin_yaw * values[1],
                sin_yaw * values[0] + cos_yaw * values[1],
                values[2],
            )

        angular_velocity = rotate_xy(sample.angular_velocity)
        linear_acceleration = rotate_xy(sample.acceleration)
        magnetometer = rotate_xy(sample.magnetometer)

        imu_msg = Imu()
        imu_msg.header.stamp = stamp
        imu_msg.header.frame_id = self.frame_id
        imu_msg.orientation.x = orientation[0]
        imu_msg.orientation.y = orientation[1]
        imu_msg.orientation.z = orientation[2]
        imu_msg.orientation.w = orientation[3]
        imu_msg.angular_velocity.x = angular_velocity[0]
        imu_msg.angular_velocity.y = angular_velocity[1]
        imu_msg.angular_velocity.z = angular_velocity[2]
        imu_msg.linear_acceleration.x = linear_acceleration[0]
        imu_msg.linear_acceleration.y = linear_acceleration[1]
        imu_msg.linear_acceleration.z = linear_acceleration[2]
        imu_msg.orientation_covariance[0] = 0.05
        imu_msg.orientation_covariance[4] = 0.05
        imu_msg.orientation_covariance[8] = 0.05
        imu_msg.angular_velocity_covariance[0] = 0.02
        imu_msg.angular_velocity_covariance[4] = 0.02
        imu_msg.angular_velocity_covariance[8] = 0.02
        imu_msg.linear_acceleration_covariance[0] = 0.1
        imu_msg.linear_acceleration_covariance[4] = 0.1
        imu_msg.linear_acceleration_covariance[8] = 0.1

        mag_msg = MagneticField()
        mag_msg.header.stamp = stamp
        mag_msg.header.frame_id = self.frame_id
        mag_msg.magnetic_field.x = float(magnetometer[0])
        mag_msg.magnetic_field.y = float(magnetometer[1])
        mag_msg.magnetic_field.z = float(magnetometer[2])

        self.imu_pub.publish(imu_msg)
        self.mag_pub.publish(mag_msg)
        self.last_publish_time = time.monotonic()

    def destroy_node(self):
        if getattr(self, "serial", None) is not None and self.serial.is_open:
            self.serial.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = WitImuNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
