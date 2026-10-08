#!/usr/bin/python
# -*- coding: UTF-8 -*-

"""
小智AI语音助手 - RDK系列
=====================================

这是一个为RDK系列平台设计的AI语音助手程序，提供实时语音交互功能。

支持板卡:
- RDK X3
- RDK X5
- RDK S100

主要功能:
- 实时语音识别和合成
- 加密音频传输
- MQTT消息通信
- 键盘交互控制
- MCP服务集成（目标检测等）

依赖库:
- paho-mqtt: MQTT客户端
- pyaudio: 音频处理
- opuslib: 音频编解码
- cryptography: 加密解密
- requests: HTTP请求

使用方法:
1. 确保音频设备正常工作
2. 运行程序: python xiaozhi-in-rdk.py
3. 按SPACE键开始录音，松开结束录音
4. 按'q'键退出程序

MCP服务支持: 基于TROS
- YOLOv8 目标检测: 支持所有RDK板卡 (X3/X5/S100)
"""

# Luka adaptation: route ROS speech before loading legacy ALSA/Opus dependencies.
import sys
if __name__ == '__main__' and '--upstream-reference' not in sys.argv:
    if '--ros-speech' in sys.argv:
        sys.argv.remove('--ros-speech')
    from luka_xiaozhi.ros_client import main
    main()
    raise SystemExit(0)
if '--upstream-reference' in sys.argv:
    sys.argv.remove('--upstream-reference')

import json
import time
import requests
import paho.mqtt.client as mqtt
import threading
import pyaudio
import opuslib
import warnings
import urllib3
import socket
import logging
import os
import errno
import ssl
import sys
import termios
import tty
import select
import uuid
import glob

# 屏蔽警告信息
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# ============================================================================
# 系统配置和环境初始化
# ============================================================================

class ALSAErrorSuppressor:
    """ALSA错误输出抑制器，防止音频库错误信息干扰用户界面"""

    def __enter__(self):
        self.old_stderr = os.dup(2)
        self.devnull = os.open('/dev/null', os.O_WRONLY)
        os.dup2(self.devnull, 2)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.dup2(self.old_stderr, 2)
        os.close(self.old_stderr)
        os.close(self.devnull)

# RDK环境配置
os.environ['DISPLAY'] = ':0'

# 日志配置 - 只记录WARNING及以上级别
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='xiaozhi.log',
    filemode='w'
)

# ============================================================================
# 程序信息和使用说明
# ============================================================================

def print_banner():
    """显示程序启动横幅和使用说明"""
    print("=" * 60)
    print("🤖 小智AI语音助手 - RDK系列")
    print("=" * 60)
    print("📋 支持板卡: RDK X3 / RDK X5 / RDK S100")
    print("💡 使用说明:")
    print("   - 按 SPACE 键开始语音输入")
    print("   - 松开 SPACE 键结束语音输入")
    print("   - 按 'q' 键退出程序")
    print("=" * 60)

# ============================================================================
# 设备识别和配置
# ============================================================================

def get_wlan0_ip():
    """
    获取wlan0接口的IP地址

    Returns:
        str: IP地址，如果未连接则返回 '127.0.0.1'
    """
    try:
        import subprocess
        result = subprocess.run(['ip', 'addr', 'show', 'wlan0'],
                              capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'inet ' in line:
                    ip = line.strip().split()[1].split('/')[0]
                    return ip
    except:
        pass
    return '127.0.0.1'

def get_system_mac_address():
    """
    获取wlan0的MAC地址作为设备唯一标识
    优先读取wlan0，如果不存在则使用其他网络接口

    Returns:
        str: 格式化的MAC地址 (xx:xx:xx:xx:xx:xx)
    """
    try:
        # 优先读取wlan0的MAC地址
        wlan0_path = '/sys/class/net/wlan0/address'
        if os.path.exists(wlan0_path):
            with open(wlan0_path, 'r') as f:
                mac = f.read().strip()
                if mac and mac != '00:00:00:00:00:00':
                    return mac
    except:
        pass

    try:
        # 方法2: 读取其他网络接口文件
        net_interfaces = glob.glob('/sys/class/net/*/address')
        for interface_path in net_interfaces:
            interface_name = interface_path.split('/')[-2]
            if interface_name != 'lo':  # 排除回环接口
                try:
                    with open(interface_path, 'r') as f:
                        mac = f.read().strip()
                        if mac and mac != '00:00:00:00:00:00':
                            return mac
                except:
                    continue
    except:
        pass

    try:
        # 方法3: 使用uuid.getnode()
        mac_int = uuid.getnode()
        mac_hex = hex(mac_int)[2:].zfill(12)
        mac_formatted = ':'.join([mac_hex[i:i+2] for i in range(0, 12, 2)])
        return mac_formatted
    except:
        pass

    # 备用MAC地址
    return '50:cf:14:5a:9f:17'

# ============================================================================
# 全局配置和状态变量
# ============================================================================

# 服务器配置
OTA_VERSION_URL = 'https://api.tenclass.net/xiaozhi/ota/'
MAC_ADDR = get_system_mac_address()

# 连接配置
RECONNECT_INTERVAL = 5  # 重连间隔（秒）
HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）

# 全局状态变量
mqtt_info = {}
last_printed_text = ""
local_sequence = 0
listen_state = None
tts_state = None
key_state = None
audio = None
udp_socket = None
conn_state = False
running = True
last_heartbeat = 0
last_listen_stop_time = None

# 线程管理
recv_audio_thread = None
send_audio_thread = None
mqtt_client = None
keyboard_thread = None

# 终端设置
old_term_settings = None

# 音频和会话配置
aes_opus_info = {
    "type": "hello",
    "version": 3,
    "transport": "udp",
    "udp": {
        "server": "120.24.160.13",
        "port": 8884,
        "encryption": "aes-128-ctr",
        "key": "263094c3aa28cb42f3965a1020cb21a7",
        "nonce": "01000000ccba9720b4bc268100000000"
    },
    "audio_params": {
        "format": "opus",
        "sample_rate": 24000,
        "channels": 1,
        "frame_duration": 60
    },
    "session_id": "b23ebfe9"
}

# 会话配置

# 会话结束消息
goodbye_msg = {
    "session_id": "b23ebfe9",
    "type": "goodbye"
}

# ============================================================================
# 终端输入处理
# ============================================================================

def init_terminal():
    """初始化终端设置，启用字符模式输入"""
    global old_term_settings
    try:
        old_term_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    except:
        print("⚠️  使用简化输入模式")
        old_term_settings = None

def restore_terminal():
    """恢复终端设置到原始状态"""
    global old_term_settings
    if old_term_settings:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_term_settings)
        except:
            pass

def get_char():
    """非阻塞获取字符输入"""
    if old_term_settings is None:
        return None

    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
        return sys.stdin.read(1)
    return None

def keyboard_listener():
    """键盘监听线程，处理空格键和退出键"""
    global running, key_state, last_listen_stop_time

    print("🎤 键盘监听已启动...")
    space_pressed = False

    while running:
        if old_term_settings:
            # 终端字符模式
            char = get_char()
            if char == ' ' and not space_pressed:
                space_pressed = True
                on_space_key_press()
            elif char != ' ' and space_pressed:
                space_pressed = False
                on_space_key_release()
            elif char == 'q':
                print("\n👋 退出程序")
                running = False
                break
        else:
            # 简化输入模式
            try:
                print("\n按 ENTER 录音，'q'退出: ", end='', flush=True)
                user_input = input().strip()
                if user_input.lower() == 'q':
                    running = False
                    break
                elif user_input == '':
                    on_space_key_press()
                    print("🎤 录音中... 按 ENTER 停止")
                    input()
                    on_space_key_release()
            except KeyboardInterrupt:
                running = False
                break

        time.sleep(0.1)

# ============================================================================
# 配置获取和更新
# ============================================================================

def get_system_hardware_info():
    """
    获取系统实际硬件信息

    Returns:
        dict: 包含flash_size和minimum_free_heap_size的字典
    """
    hardware_info = {
        "flash_size": 16777216,        # 默认值 16MB
        "minimum_free_heap_size": 8318916  # 默认值 8MB
    }

    try:
        # 获取Flash存储信息 (eMMC/SD卡大小)
        import shutil
        total, used, free = shutil.disk_usage('/')
        # 将根分区大小作为Flash大小参考
        hardware_info["flash_size"] = total

    except Exception as e:
        logging.warning(f"无法获取Flash大小信息: {str(e)}")

    try:
        # 获取内存信息
        with open('/proc/meminfo', 'r') as f:
            meminfo = f.read()

        # 解析MemAvailable (系统可用内存)
        for line in meminfo.split('\n'):
            if line.startswith('MemAvailable:'):
                # 提取数值，单位是kB
                mem_available_kb = int(line.split()[1])
                # 转换为字节，取80%作为最小可用堆大小
                hardware_info["minimum_free_heap_size"] = int(mem_available_kb * 1024 * 0.8)
                break
        else:
            # 如果没有MemAvailable，使用MemFree
            for line in meminfo.split('\n'):
                if line.startswith('MemFree:'):
                    mem_free_kb = int(line.split()[1])
                    hardware_info["minimum_free_heap_size"] = int(mem_free_kb * 1024 * 0.8)
                    break

    except Exception as e:
        logging.warning(f"无法获取内存信息: {str(e)}")

    # 记录获取到的硬件信息
    logging.info(f"Flash大小: {hardware_info['flash_size'] / (1024*1024):.1f}MB")
    logging.info(f"最小可用堆: {hardware_info['minimum_free_heap_size'] / (1024*1024):.1f}MB")

    return hardware_info

def get_ota_version():
    """
    从服务器获取OTA版本信息和MQTT配置
    包含设备信息上报和配置更新
    """
    global mqtt_info

    # 获取实际硬件信息
    hardware_info = get_system_hardware_info()

    header = {
        'Device-Id': MAC_ADDR,
        'Content-Type': 'application/json'
    }

    # 设备信息数据
    post_data = {
        "flash_size": hardware_info["flash_size"],
        "minimum_free_heap_size": hardware_info["minimum_free_heap_size"],
        "mac_address": MAC_ADDR,
        "chip_model_name": "rdk",
        "chip_info": {
            "model": "RDK",
            "cores": 8,
            "revision": 1,
            "features": 32
        },
        "application": {
            "name": "xiaozhi",
            "version": "1.1.0-rdk",
            "compile_time": "Oct 15 2025",
            "idf_version": "rdk-1.1",
            "elf_sha256": "22986216df095587c42f8aeb06b239781c68ad8df80321e260556da7fcf5f522"
        },
        "partition_table": [],
        "ota": {"label": "factory"},
        "board": {
            "type": "rdk-dev",
            "ssid": "RDK-WiFi",
            "rssi": -45,
            "channel": 6,
            "ip": "192.168.1.100",
            "mac": "rdk:device:mac"
        }
    }

    try:
        response = requests.post(OTA_VERSION_URL, headers=header,
                               data=json.dumps(post_data), timeout=10, verify=False)
        response.raise_for_status()
        mqtt_info = response.json()['mqtt']
        print("✅ 配置更新成功")
        logging.info("配置更新成功")
    except Exception as e:
        print(f"❌ 配置更新失败: {str(e)}")
        logging.error(f"配置更新失败: {str(e)}")
        time.sleep(RECONNECT_INTERVAL)
        get_ota_version()

# ============================================================================
# 加密解密功能
# ============================================================================

def aes_ctr_encrypt(key, nonce, plaintext):
    """AES-CTR模式加密"""
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()

def aes_ctr_decrypt(key, nonce, ciphertext):
    """AES-CTR模式解密"""
    cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
    decryptor = cipher.decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext

# ============================================================================
# 音频处理
# ============================================================================


def send_audio():
    """音频发送线程 - 录制麦克风音频并发送到服务器"""
    global aes_opus_info, udp_socket, local_sequence, listen_state, audio, running

    key = aes_opus_info['udp']['key']
    nonce = aes_opus_info['udp']['nonce']
    server_ip = aes_opus_info['udp']['server']
    server_port = aes_opus_info['udp']['port']

    # 创建Opus编码器
    encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_AUDIO)

    mic = None
    try:
        # 打开麦克风流
        with ALSAErrorSuppressor():
            mic = audio.open(format=pyaudio.paInt16, channels=1, rate=16000,
                            input=True, frames_per_buffer=960,
                            stream_callback=None)

        if mic is None:
            logging.error("无法打开麦克风设备")
            print("❌ 麦克风设备打开失败")
            return

        while running and aes_opus_info['session_id']:
            if listen_state == "stop":
                time.sleep(0.1)
                continue

            # 读取音频数据 (添加 exception_on_overflow=False 防止缓冲区溢出错误)
            try:
                data = mic.read(960, exception_on_overflow=False)
            except IOError as e:
                if e.errno == pyaudio.paInputOverflowed:
                    logging.warning("音频输入溢出，跳过此帧")
                    continue
                else:
                    raise

            encoded_data = encoder.encode(data, 960)

            # 构建加密nonce
            local_sequence += 1
            new_nonce = (nonce[0:4] + format(len(encoded_data), '04x') +
                        nonce[8:24] + format(local_sequence, '08x'))

            # 加密音频数据
            encrypt_encoded_data = aes_ctr_encrypt(
                bytes.fromhex(key),
                bytes.fromhex(new_nonce),
                bytes(encoded_data)
            )

            # 发送到服务器
            data = bytes.fromhex(new_nonce) + encrypt_encoded_data
            try:
                udp_socket.sendto(data, (server_ip, server_port))
            except socket.error as e:
                if e.errno == errno.ENETUNREACH:
                    restart_audio_streams()
                    break
                elif e.errno == errno.EBADF:  # Bad file descriptor - socket已关闭
                    logging.info("UDP socket已关闭，停止发送")
                    break
                else:
                    raise
    except Exception as e:
        # 如果程序正在退出，只记录日志，不打印错误
        if running:
            logging.error(f"音频发送错误: {str(e)}")
            print(f"❌ 录音设备错误: {str(e)}")
        else:
            logging.info(f"程序退出时音频发送停止: {str(e)}")
    finally:
        if mic is not None:
            try:
                mic.stop_stream()
                mic.close()
            except:
                pass

def recv_audio():
    """音频接收线程 - 接收服务器音频并播放"""
    global aes_opus_info, udp_socket, audio, running

    key = aes_opus_info['udp']['key']
    sample_rate = aes_opus_info['audio_params']['sample_rate']
    frame_duration = aes_opus_info['audio_params']['frame_duration']
    frame_num = int(frame_duration / (1000 / sample_rate))

    # 创建Opus解码器
    decoder = opuslib.Decoder(sample_rate, 1)

    spk = None
    try:
        # 使用指定采样率打开扬声器
        with ALSAErrorSuppressor():
            spk = audio.open(format=pyaudio.paInt16, channels=1, rate=sample_rate,
                            output=True, frames_per_buffer=frame_num,
                            stream_callback=None, start=False)

        if spk is None:
            logging.error("无法打开音频播放设备")
            return

        # 预填充静音数据减少延迟
        silence = b'\x00' * (frame_num * 2)
        spk.start_stream()
        spk.write(silence)

        while running and aes_opus_info['session_id']:
            try:
                # 接收加密音频数据
                data, server = udp_socket.recvfrom(4096)
                split_nonce = data[:16]
                encrypt_data = data[16:]

                # 解密音频数据
                decrypt_data = aes_ctr_decrypt(
                    bytes.fromhex(key),
                    split_nonce,
                    encrypt_data
                )

                # 解码并播放
                spk.write(decoder.decode(decrypt_data, frame_num))
            except socket.timeout:
                continue
            except Exception as e:
                logging.error(f"音频接收错误: {str(e)}")
    except Exception as e:
        logging.error(f"播放流初始化失败: {str(e)}")
        print(f"❌ 播放设备错误: {str(e)}")
    finally:
        if spk is not None:
            try:
                spk.stop_stream()
                spk.close()
            except:
                pass

def restart_audio_streams():
    """重启音频流连接"""
    global aes_opus_info, recv_audio_thread, send_audio_thread, udp_socket

    # 清理现有连接
    if udp_socket:
        udp_socket.close()
    if recv_audio_thread and recv_audio_thread.is_alive():
        recv_audio_thread.join(timeout=2)
    if send_audio_thread and send_audio_thread.is_alive():
        send_audio_thread.join(timeout=2)

    try:
        # 创建新的UDP连接
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.settimeout(1)
        udp_socket.connect((aes_opus_info['udp']['server'], aes_opus_info['udp']['port']))

        # 启动音频线程（接收线程优先）
        recv_audio_thread = threading.Thread(target=recv_audio, daemon=True)
        recv_audio_thread.start()
        time.sleep(0.1)

        send_audio_thread = threading.Thread(target=send_audio, daemon=True)
        send_audio_thread.start()
    except Exception as e:
        logging.error(f"UDP连接失败: {str(e)}")

# ============================================================================
# MQTT消息处理
# ============================================================================

def on_mqtt_message(client, userdata, msg):
    """MQTT消息处理回调函数"""
    global aes_opus_info, udp_socket, tts_state, recv_audio_thread, send_audio_thread, last_printed_text

    try:
        message = json.loads(msg.payload)
        logging.info(f"接收到 MQTT 消息: {message}")

        message_type = message.get('type')

        if message_type == 'hello':
            handle_hello_message(message)
        elif message_type == 'tts':
            handle_tts_message(message)
        elif message_type == 'stt':
            handle_stt_message(message)
        elif message_type == 'llm':
            handle_llm_message(message)
        elif message_type == 'goodbye':
            handle_goodbye_message(message)

    except Exception as e:
        print(f"❌ 消息处理错误: {str(e)}")
        logging.error(f"消息处理错误: {str(e)}")

def handle_hello_message(message):
    """处理HELLO消息，建立会话连接"""
    global aes_opus_info

    if not aes_opus_info['session_id']:
        aes_opus_info['session_id'] = message.get('session_id', None)

    aes_opus_info['udp'] = message.get('udp', aes_opus_info['udp'])
    logging.info(f"处理 HELLO 消息完成，session_id: {aes_opus_info['session_id']}")
    restart_audio_streams()

def handle_tts_message(message):
    """处理TTS（文本转语音）消息"""
    global tts_state, last_printed_text

    tts_state = message['state']
    if tts_state == 'start':
        print("🔊 播放中...")
    elif tts_state == 'sentence_start':
        # 显示AI回复文本
        sentence_text = message.get('text', '')
        if sentence_text and sentence_text != last_printed_text:
            print(f"🤖 地瓜派: {sentence_text}")
            last_printed_text = sentence_text
    elif tts_state == 'stop':
        print("✅ 播放完成")
        last_printed_text = ""

def handle_stt_message(message):
    """处理STT（语音转文本）消息"""
    stt_text = message.get('text', '')
    if stt_text:
        print(f"👤 用户: {stt_text}")

def handle_llm_message(message):
    """处理LLM回复消息"""
    global last_printed_text

    llm_text = message.get('text', '')
    if llm_text and llm_text != last_printed_text:
        print(f"🤖 地瓜派: {llm_text}")
        last_printed_text = llm_text

def handle_goodbye_message(message):
    """处理GOODBYE消息，结束会话"""
    global aes_opus_info, udp_socket

    if message.get('session_id') == aes_opus_info['session_id']:
        aes_opus_info['session_id'] = None
        if udp_socket:
            udp_socket.close()
        print("👋 会话结束")
        logging.info("会话已结束")

# ============================================================================
# MQTT连接管理
# ============================================================================

def on_mqtt_connect(client, userdata, flags, rc):
    """MQTT连接成功回调"""
    if rc == 0:
        print("✅ MQTT连接成功")
        result = client.subscribe(mqtt_info['subscribe_topic'], qos=0)
        logging.info(f"MQTT连接成功，订阅结果: {result}")
    else:
        print(f"❌ MQTT连接失败，错误码: {rc}")
        logging.error(f"MQTT连接失败，错误码: {rc}")

def on_mqtt_disconnect(client, userdata, rc):
    """MQTT断开连接回调"""
    global running

    # 如果程序正在退出，不尝试重连
    if not running:
        logging.info("程序退出，跳过MQTT重连")
        return

    print("⚠️  MQTT断开，重连中...")
    logging.warning("MQTT连接断开，正在尝试重连...")
    time.sleep(RECONNECT_INTERVAL)
    try:
        if running:  # 再次检查running状态
            client.reconnect()
    except:
        pass

def setup_mqtt():
    """设置MQTT连接"""
    global mqtt_client

    # 清理旧连接
    if mqtt_client:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except:
            pass

    # 创建新客户端
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                             client_id=mqtt_info['client_id'])
    mqtt_client.username_pw_set(mqtt_info['username'], mqtt_info['password'])

    # SSL/TLS配置
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    mqtt_client.tls_set_context(context=ssl_context)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_disconnect = on_mqtt_disconnect
    mqtt_client.on_message = on_mqtt_message

    try:
        mqtt_client.connect(mqtt_info['endpoint'], 8883, 60)
        mqtt_client.loop_start()
        logging.info("MQTT连接已初始化")
    except Exception as e:
        print(f"❌ MQTT初始化失败: {str(e)}")
        logging.error(f"MQTT连接初始化失败: {str(e)}")

# ============================================================================
# 心跳和会话管理
# ============================================================================

def send_heartbeat():
    """心跳和会话超时检查线程"""
    global last_heartbeat, running, last_listen_stop_time

    while running:
        # 发送心跳
        if (time.time() - last_heartbeat > HEARTBEAT_INTERVAL and
            mqtt_client and mqtt_client.is_connected()):
            try:
                mqtt_client.publish(mqtt_info['publish_topic'],
                                  json.dumps({"type": "heartbeat"}))
                last_heartbeat = time.time()
                logging.info("心跳已发送")
            except Exception as e:
                logging.error(f"心跳发送失败: {str(e)}")

        # 检查会话超时
        if (last_listen_stop_time is not None and
            time.time() - last_listen_stop_time > 5):
            logging.info("会话超时，关闭会话")
            handle_goodbye_message(goodbye_msg)
            last_listen_stop_time = None

        time.sleep(1)

# ============================================================================
# 用户交互处理
# ============================================================================

def on_space_key_press():
    """空格键按下处理 - 开始录音"""
    global key_state, listen_state, aes_opus_info

    key_state = "press"
    logging.info("开始监听")

    if not aes_opus_info['session_id']:
        print("🔗 连接会话...")
        send_hello_message()
        time.sleep(0.5)

    print("🎤 倾听中...")
    send_listen_message("start")

def on_space_key_release():
    """空格键松开处理 - 结束录音"""
    global key_state, last_listen_stop_time

    key_state = "release"
    print("⏹️  等待回复...")
    logging.info("结束监听")

    send_listen_message("stop")
    last_listen_stop_time = time.time()

def send_hello_message():
    """发送HELLO消息建立会话"""
    hello_msg = {
        "type": "hello",
        "version": 3,
        "transport": "udp",
        "audio_params": {
            "format": "opus",
            "sample_rate": 16000,
            "channels": 1,
            "frame_duration": 60
        }
    }
    try:
        mqtt_client.publish(mqtt_info['publish_topic'], json.dumps(hello_msg))
        logging.info("HELLO 消息已发送")
    except Exception as e:
        logging.error(f"HELLO 消息发送失败: {str(e)}")

def send_listen_message(state):
    """发送LISTEN消息控制录音状态"""
    if aes_opus_info['session_id']:
        msg = {
            "session_id": aes_opus_info['session_id'],
            "type": "listen",
            "state": state,
            "mode": "manual"
        }
        try:
            mqtt_client.publish(mqtt_info['publish_topic'], json.dumps(msg))
            logging.info(f"LISTEN 消息已发送，状态: {state}")
        except Exception as e:
            logging.error(f"LISTEN 消息发送失败: {str(e)}")

# ============================================================================
# 主程序入口
# ============================================================================

def run():
    """主程序运行函数"""
    global audio, running, keyboard_thread

    try:
        # 显示程序信息
        print_banner()
        print(f"🏷️  设备MAC地址: {MAC_ADDR}")

        # 获取并显示wlan0 IP地址
        wlan0_ip = get_wlan0_ip()
        if wlan0_ip == '127.0.0.1':
            print(f"⚠️  wlan0未连接，使用: {wlan0_ip}")
        else:
            print(f"📡 wlan0 IP地址: {wlan0_ip}")

        # 初始化音频系统
        print("🚀 初始化音频...")
        with ALSAErrorSuppressor():
            audio = pyaudio.PyAudio()

        # 获取服务器配置
        print("🌐 获取配置...")
        get_ota_version()

        # 连接MQTT服务
        print("📡 连接服务...")
        setup_mqtt()

        # 启动心跳线程
        print("💓 启动心跳...")
        threading.Thread(target=send_heartbeat, daemon=True).start()

        # 启动键盘监听
        print("⌨️  启动监听...")
        init_terminal()
        keyboard_thread = threading.Thread(target=keyboard_listener, daemon=True)
        keyboard_thread.start()

        print("✨ 启动完成!")
        print("=" * 60)

        # 主循环
        try:
            while running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n🛑 中断退出")
            running = False

    except Exception as e:
        print(f"❌ 运行错误: {str(e)}")
        logging.error(f"运行时错误: {str(e)}")
    finally:
        # 清理资源
        print("\n🧹 清理资源...")
        running = False

        # 1. 先停止MQTT（防止重连）
        if mqtt_client:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
                logging.info("MQTT连接已关闭")
            except Exception as e:
                logging.warning(f"MQTT关闭异常: {str(e)}")

        # 2. 等待音频线程结束
        if send_audio_thread and send_audio_thread.is_alive():
            send_audio_thread.join(timeout=2)
        if recv_audio_thread and recv_audio_thread.is_alive():
            recv_audio_thread.join(timeout=2)

        # 3. 关闭UDP socket
        if udp_socket:
            try:
                udp_socket.close()
                logging.info("UDP连接已关闭")
            except Exception as e:
                logging.warning(f"UDP关闭异常: {str(e)}")

        # 4. 终止音频系统
        if audio:
            try:
                audio.terminate()
                logging.info("音频系统已终止")
            except Exception as e:
                logging.warning(f"音频系统终止异常: {str(e)}")

        # 5. 恢复终端设置
        restore_terminal()

        logging.info("资源清理完成")
        print("👋 程序退出")

if __name__ == "__main__":
    run()
