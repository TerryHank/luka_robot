#!/usr/bin/env python3
"""
ROS2 节点：将 /cmd_vel (Twist) 转换为 DDSM 四轮差速电机指令

四轮差速逆运动学 (Skid-Steer 4WD)：
  给定 robot 线速度 v (m/s) 和角速度 ω (rad/s)，
  每个车轮的线速度：
    v_i = v - ω * y_i
  其中 y_i 为车轮相对于机器人中心的横向距离。

  左侧车轮 (1, 3): y = +W/2，前进方向正转 cmd
  右侧车轮 (2, 4): y = -W/2，前进方向反转 cmd

  RPM = v_linear / (π * D) * 60

车辆参数：
  轮距 W = 355 mm = 0.355 m
  轴距 L = 310 mm = 0.310 m
  轮径 D = 75 mm  = 0.075 m

用法：
  ros2 run ddsm_car_control cmd_vel_to_ddsm
  ros2 run ddsm_car_control cmd_vel_to_ddsm --ros-args -p host:=192.168.3.139 -p port:=81
"""

import math
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist

from .ddsm_driver import DDSMDriver


# ── 四轮差速逆运动学 ──────────────────────────────────────────────

def inverse_kinematics(v: float, omega: float,
                       track_width: float = 0.355,
    wheel_diameter: float = 0.1016,
                       directions: dict = None,
                       max_rpm: float = 200.0,
                       deadband: float = 0.01) -> dict:
    """
    四轮差速逆运动学：将 body twist 转换为各电机转速。

    Args:
        v:             机器人线速度 (m/s)，前进为正
        omega:         机器人角速度 (rad/s)，逆时针为正
        track_width:   轮距 (m)，左右轮中心间距，默认 0.355
        wheel_diameter: 轮径 (m)，默认 0.1016
        directions:    {motor_id: sign}，+1=正转前进，-1=反转前进
        max_rpm:       最大转速限制 (RPM)
        deadband:      死区阈值 (m/s 或 rad/s)，低于此值设零

    Returns:
        {motor_id: cmd_rpm, ...}  例如 {1: 50, 2: -50, 3: 50, 4: -50}
    """
    if directions is None:
        directions = {1: 1, 2: -1, 3: 1, 4: -1}

    # 死区处理：微小速度直接置零
    if abs(v) < deadband and abs(omega) < deadband:
        return {i: 0 for i in directions}

    # RPM 转换因子: linear_speed (m/s) -> wheel RPM
    # RPM = v / (π * D) * 60
    rpm_factor = 60.0 / (math.pi * wheel_diameter)

    half_track = track_width / 2.0

    # 左右侧车轮线速度 (m/s)
    v_left = v - omega * half_track   # 左轮
    v_right = v + omega * half_track  # 右轮

    # 转换为 RPM
    rpm_left = v_left * rpm_factor
    rpm_right = v_right * rpm_factor

    # 限制最大转速
    rpm_left = max(-max_rpm, min(max_rpm, rpm_left))
    rpm_right = max(-max_rpm, min(max_rpm, rpm_right))

    # 应用各电机方向符号，生成最终 cmd
    # 左侧电机 (正向=前进)，右侧电机 (反向=前进)
    cmds = {}
    for motor_id, sign in directions.items():
        if sign > 0:
            cmds[motor_id] = round(rpm_left)
        else:
            cmds[motor_id] = round(-rpm_right)

    return cmds


# ── ROS2 节点 ─────────────────────────────────────────────────────

class CmdVelToDDSM(Node):
    """
    订阅 /cmd_vel，通过逆运动学计算四轮转速，经 TCP 发送到 DDSM 驱动板。

    参数 (均可通过 ROS2 params 覆盖):
        host:           ESP32 IP 地址 (默认 192.168.3.139)
        port:           TCP 端口 (默认 81)
        track_width:    轮距 (m)，默认 0.355
        wheel_diameter: 轮径 (m)，默认 0.1016
        max_rpm:        最大转速 (RPM)，默认 200
        cmd_freq:       指令发送频率 (Hz)，默认 50
        heartbeat_ms:   心跳超时 (ms)，0 表示不设置，默认 2000
        timeout:        无 cmd_vel 后多久停车 (秒)，默认 0.5
    """

    def __init__(self):
        super().__init__('cmd_vel_to_ddsm')

        # ── 参数声明 ──
        self.declare_parameter('host', '192.168.3.139')
        self.declare_parameter('port', 80)
        self.declare_parameter('track_width', 0.355)
        self.declare_parameter('wheel_diameter', 0.1016)
        self.declare_parameter('max_rpm', 200.0)
        self.declare_parameter('cmd_freq', 50.0)
        self.declare_parameter('heartbeat_ms', 2000)
        self.declare_parameter('timeout', 0.5)
        self.declare_parameter('act', 3)

        host = self.get_parameter('host').value
        port = self.get_parameter('port').value
        self.track_width = self.get_parameter('track_width').value
        self.wheel_diameter = self.get_parameter('wheel_diameter').value
        self.max_rpm = self.get_parameter('max_rpm').value
        self.heartbeat_ms = self.get_parameter('heartbeat_ms').value
        self.timeout = self.get_parameter('timeout').value
        self.act = self.get_parameter('act').value

        # 电机方向符号：前进时 1/3 正转 (+1)，2/4 反转 (-1)
        self.directions = {1: 1, 2: -1, 3: 1, 4: -1}

        # ── DDSM 驱动 ──
        self.driver = DDSMDriver(host=host, port=port, timeout=1.0)

        # ── 状态 ──
        self._last_cmd_vel = None   # 最近的 Twist 消息
        self._last_cmd_time = self.get_clock().now()
        self._current_rpm = {1: 0, 2: 0, 3: 0, 4: 0}

        # ── 连接并初始化 ──
        self._connect_and_init()

        # ── 订阅 /cmd_vel ──
        self.sub = self.create_subscription(
            Twist, 'cmd_vel', self._cmd_vel_callback, 10)

        # ── 定时器：按固定频率发送指令 ──
        cmd_freq = self.get_parameter('cmd_freq').value
        period = 1.0 / cmd_freq
        self._timer = self.create_timer(period, self._timer_callback)

        self.get_logger().info(
            f'CmdVelToDDSM ready | host={host}:{port} | '
            f'track={self.track_width}m wheel={self.wheel_diameter}m '
            f'max_rpm={self.max_rpm} | act={self.act} | cmd_freq={cmd_freq}Hz'
        )

    def _connect_and_init(self):
        """建立 TCP 连接并初始化驱动板"""
        try:
            self.driver.connect()
            self.get_logger().info(
                f'Connected to {self.driver.host}:{self.driver.port}')

            # 设置心跳（防止通信中断时电机继续转）
            if self.heartbeat_ms > 0:
                self.driver.set_heartbeat(self.heartbeat_ms)
                self.get_logger().info(
                    f'Heartbeat set to {self.heartbeat_ms}ms')

        except Exception as e:
            self.get_logger().error(f'Connection failed: {e}')
            self.get_logger().warn(
                'Will retry connection on next timer tick...')

    def _cmd_vel_callback(self, msg: Twist):
        """接收 /cmd_vel 指令"""
        self._last_cmd_vel = msg
        self._last_cmd_time = self.get_clock().now()

    def _timer_callback(self):
        """
        定时发送电机指令。

        1. 检查连接状态，断线则尝试重连
        2. 检查最后收到 cmd_vel 的时间，超时则停车
        3. 逆运动学计算 → 发送
        """
        # 重连处理
        if not self.driver.connected:
            self.get_logger().warn('Connection lost, retrying...', throttle_duration_sec=5.0)
            try:
                self.driver.connect()
                if self.heartbeat_ms > 0:
                    self.driver.set_heartbeat(self.heartbeat_ms)
                self.get_logger().info('Reconnected')
            except Exception:
                return  # 等下一轮

        # 超时检查
        elapsed = (self.get_clock().now() - self._last_cmd_time).nanoseconds / 1e9
        if self._last_cmd_vel is None or elapsed > self.timeout:
            # 无指令或超时 → 停车
            target = {1: 0, 2: 0, 3: 0, 4: 0}
        else:
            v = self._last_cmd_vel.linear.x
            omega = self._last_cmd_vel.angular.z
            target = inverse_kinematics(
                v, omega,
                track_width=self.track_width,
                wheel_diameter=self.wheel_diameter,
                directions=self.directions,
                max_rpm=self.max_rpm,
            )

        # 只在转速变化时发送（减少不必要的网络流量）
        if target != self._current_rpm:
            self._current_rpm = target
            self.driver.set_speeds(target, act=self.act)

    def destroy_node(self):
        """节点销毁时停车并断开连接"""
        self.get_logger().info('Stopping motors and disconnecting...')
        try:
            self.driver.stop_all()
        except Exception:
            pass
        self.driver.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CmdVelToDDSM()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
