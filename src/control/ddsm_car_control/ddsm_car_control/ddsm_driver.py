"""
DDSM Driver HAT (A) HTTP 通信层

通过 HTTP GET 向 ESP32 发送 JSON 指令控制 DDSM 轮毂电机。
ESP32 Web 应用通过 /js?json=... 端点接收 JSON 指令。

用法:
    driver = DDSMDriver(host='192.168.3.139', port=80)
    driver.set_heartbeat(2000)
    driver.set_speed(1, 50)              # 电机1: 50 RPM
    driver.set_speeds({1: 50, 2: -50, 3: 50, 4: -50})
"""

import json
import logging
import urllib.request
import urllib.error
from threading import Lock

logger = logging.getLogger(__name__)

# JSON 指令类型常量
CMD_DDSM_CTRL = 10010
CMD_HEARTBEAT = 11001
CMD_CHANGE_MODE = 10012
CMD_SET_TYPE = 11002
CMD_ID_CHECK = 10031


class DDSMDriver:
    """
    DDSM Driver HAT HTTP 驱动。

    通过 HTTP GET /js?json=... 发送 JSON 指令。
    """

    DEFAULT_DIRECTIONS = {1: 1, 2: -1, 3: 1, 4: -1}

    def __init__(self, host='192.168.3.139', port=80, timeout=0.5):
        self.base_url = f'http://{host}:{port}'
        self.timeout = timeout
        self._lock = Lock()
        self._connected = True  # HTTP 无状态，始终视为可用
        self.host = host
        self.port = port

    def connect(self):
        """HTTP 无需连接，仅做连通性检查"""
        try:
            self._send_cmd_raw({'T': CMD_ID_CHECK})
            self._connected = True
            logger.info(f"DDSM HTTP endpoint OK: {self.base_url}")
            return True
        except Exception as e:
            self._connected = False
            logger.warning(f"DDSM endpoint check failed: {e}")
            return False

    def close(self):
        """HTTP 无需断开"""
        pass

    @property
    def connected(self):
        return self._connected

    def _send_cmd_raw(self, data: dict) -> dict:
        """
        发送 JSON 指令并返回响应。

        Args:
            data: JSON 字典

        Returns:
            响应 JSON 字典，失败返回 {}
        """
        json_str = json.dumps(data, separators=(',', ':'))
        url = f'{self.base_url}/js?json={urllib.request.quote(json_str)}'

        try:
            with self._lock:
                req = urllib.request.Request(url)
                req.add_header('User-Agent', 'DDSM-ROS2/1.0')
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode('utf-8', errors='replace')
                    if body:
                        return json.loads(body)
                    return {}
        except urllib.error.URLError as e:
            logger.error(f"HTTP request failed: {e}")
            self._connected = False
            return {}
        except json.JSONDecodeError:
            return {}
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {}

    def set_speed(self, motor_id: int, speed_rpm: float, act: int = 3):
        """
        控制单个电机速度。

        Args:
            motor_id: 电机 ID (1~4)
            speed_rpm: 目标转速 (RPM)，DDSM115 范围约 -200~200
            act: 加速时间 (0.1ms)，默认 3
        """
        cmd = round(speed_rpm)
        self._send_cmd_raw({"T": CMD_DDSM_CTRL, "id": motor_id, "cmd": cmd, "act": act})

    def set_speeds(self, speeds: dict, act: int = 3):
        """
        批量控制多个电机速度。

        Args:
            speeds: {motor_id: speed_rpm, ...}
            act: 加速时间
        """
        for mid, rpm in speeds.items():
            self.set_speed(mid, rpm, act)

    def stop_all(self):
        """停止所有电机"""
        for i in range(1, 5):
            self.set_speed(i, 0, act=1)

    def set_heartbeat(self, time_ms: int = 2000):
        """
        设置心跳超时。

        Args:
            time_ms: 超时毫秒数，默认 2000，-1 关闭
        """
        self._send_cmd_raw({"T": CMD_HEARTBEAT, "time": time_ms})

    def set_motor_mode(self, motor_id: int, mode: int = 2):
        """
        切换电机控制模式。

        Args:
            motor_id: 电机 ID
            mode: 0=开环, 1=电流环, 2=速度环(默认), 3=位置环
        """
        self._send_cmd_raw({"T": CMD_CHANGE_MODE, "id": motor_id, "mode": mode})

    def set_motor_type(self, motor_type: int = 115):
        """
        设置驱动板电机型号。

        Args:
            motor_type: 115 (DDSM115) 或 210 (DDSM210)
        """
        self._send_cmd_raw({"T": CMD_SET_TYPE, "type": motor_type})
