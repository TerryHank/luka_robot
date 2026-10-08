import time,os,socket,json
from std_msgs.msg import String
from .arbitration import SENSORS

def tick(self):
        now=time.monotonic()
        if now-self.joy_at>.25: self.armed=False
        if not (self.armed and self.held and now-self.cmd_at<.25 and now-self.feedback_at<.5):
            self.latest_manual_cmd=None
        web_state=self.web_state
        if web_state is not None and now-web_state[2]<.30 and not self.held:
            if self.motion_paused:
                status='底盘暂停'
            elif now-self.feedback_at>.5:
                status='编码器数据过期'
            elif any(now-self.scan_times.get(topic,0)>.5 for topic in SENSORS):
                ages = [now-self.scan_times.get(topic,0) for topic in SENSORS]
                status='雷达数据过期（高位%s，低位%s）' % tuple(
                    '未收到' if age > 60 else '%.2f秒' % age for age in ages
                )
            elif self.web_motion_blocked(web_state):
                status='近距离障碍，已停车'
            else:
                status='行驶中'
                if self.web_state is web_state:
                    self.latest_manual_cmd=web_state[0]
                    self.last_manual_cmd_time=self.get_clock().now()
            self.web_status=status
        elif web_state is not None and self.web_state is web_state:
            self.web_state=None
            self.web_status='指令超时，已停车'
        if self.web_status_at==0. or now-self.web_status_at>.4:
            self.web_status_pub.publish(String(data=self.web_status))
            self.web_status_at=now
        if self.nav_allowed:
            if not self.navigation_ready():
                self.latest_nav_cmd=None
                if self.nav_bad_since is None:
                    self.nav_bad_since=now
                    self.get_logger().warn('Navigation paused: '+self.nav_reason)
                if now-self.nav_bad_since>2.:self.cancel_navigation()
            else:
                if self.nav_bad_since is not None:self.get_logger().info('Fresh navigation inputs restored')
                self.nav_bad_since=None
        if self.follow_allowed:
            if not self.follow_ready():
                self.follow_allowed=False
                self.follow_cmd=None
                self.get_logger().warn('Follow stopped: '+self.follow_reason)
            elif now-self.follow_at>.6:
                self.follow_allowed=False
                self.follow_cmd=None
                self.get_logger().warn('Follow stopped: command watchdog expired')
            elif self.follow_cmd is not None and now-self.follow_at<.25:
                self.latest_nav_cmd=self.follow_cmd
                self.last_nav_cmd_time=self.get_clock().now()
            else:
                self.latest_nav_cmd=None
        if not (self.nav_allowed or self.follow_allowed) or (self.nav_allowed and now-self.nav_at>.25):self.latest_nav_cmd=None
        healthy=self.navigation_ready() and not self.motion_paused
        self.motion_status.publish(String(data=json.dumps({'healthy':healthy,
            'manual_active':bool(self.held or self.web_state), 'nav_allowed':self.nav_allowed,
            'follow_allowed':self.follow_allowed,'reason':self.nav_reason})))
        self.driver.on_command_timer()
        address=os.environ.get('NOTIFY_SOCKET')
        if address:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
                sock.sendto(b'WATCHDOG=1', '\0'+address[1:] if address.startswith('@') else address)
