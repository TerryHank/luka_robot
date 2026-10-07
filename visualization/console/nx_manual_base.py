"""Manual-only NX adapter. No navigation commands, measured odometry only."""
import json, math, os, socket, sys, time
import copy
from pathlib import Path
sys.path.insert(0, '/home/sunrise/luka_ws/control/ddsm_car_control')
import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import Joy, LaserScan
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from std_srvs.srv import SetBool
from action_msgs.srv import CancelGoal
from tf2_ros import Buffer, TransformListener
from rclpy.qos import qos_profile_sensor_data
from ddsm_car_control.zdt_mecanum_rs485_bridge import ZDTMecanumRS485Bridge
from web_teleop_safety import SENSORS, nearby_points, blocked, follow_motion_blocked

STATE=Path('/home/sunrise/luka_ws/common/config/nx_manual_odom.json')

class ManualBase(ZDTMecanumRS485Bridge):
    def __init__(self):
        self.armed=False
        self.joy_at=self.cmd_at=self.feedback_at=0.
        self.held=False
        self.nav_allowed=False
        self.nav_at=0.
        self.follow_allowed=False
        self.follow_at=0.
        self.follow_cmd=None
        self.nav_bad_since=None
        self.scan_times={}
        self.scan_points={}
        self.web_state=None
        self.web_status='待命'
        self.web_status_at=0.
        super().__init__()
        if STATE.exists():
            state=json.loads(STATE.read_text())
            self.odom.x,self.odom.y,self.odom.yaw=state['x'],state['y'],state['yaw']
        self.create_subscription(Joy, '/joy', self.joy_input, qos_profile_sensor_data)
        self.create_timer(.5,self.checkpoint)
        self.nav_cancel=self.create_client(CancelGoal,'/navigate_to_pose/_action/cancel_goal')
        self.control_group=MutuallyExclusiveCallbackGroup()
        self.create_service(SetBool,'/nx/navigation_enable',self.enable_navigation,callback_group=self.control_group)
        self.create_service(SetBool,'/nx/follow_enable',self.enable_follow,callback_group=self.control_group)
        # Serial command/feedback timers can occupy the bridge's default
        # callback group. Nav2 velocity commands need their own executor lane
        # or the 250 ms motor watchdog discards them between callbacks.
        self.nav_group=MutuallyExclusiveCallbackGroup()
        self.destroy_subscription(self.nav_cmd_sub)
        self.nav_cmd_sub=self.create_subscription(
            Twist,self.nav_cmd_vel_topic,self.on_nav_cmd_vel,10,callback_group=self.nav_group
        )
        # Serial feedback and command timers use the default callback group.
        # Keep follow commands on their own executor lane, as for Nav2, so
        # they reach the motor watchdog before its 600 ms deadline.
        self.follow_group=MutuallyExclusiveCallbackGroup()
        self.create_subscription(Twist,'/nx/follow_safe',self.on_follow_cmd_vel,10,
                                 callback_group=self.follow_group)
        self.tf_buffer=Buffer()
        self.tf_node=rclpy.create_node('nx_base_tf_listener')
        self.tf_listener=TransformListener(self.tf_buffer,self.tf_node,spin_thread=True)
        self.scan_group=MutuallyExclusiveCallbackGroup()
        self.web_group=MutuallyExclusiveCallbackGroup()
        for topic in ('/scan','/scan_low_filtered'):
            self.create_subscription(LaserScan,topic,lambda m,t=topic:self.scan_input(t,m),qos_profile_sensor_data,callback_group=self.scan_group)
        self.create_subscription(Twist,'/nx/web_teleop_cmd_vel',self.on_web_cmd_vel,10,callback_group=self.web_group)
        self.web_status_pub=self.create_publisher(String,'/nx/web_teleop_status',10)

    def on_web_cmd_vel(self,msg):
        """Web commands are a separate, capped manual source with their own lease."""
        values=(msg.linear.x,msg.linear.y,msg.angular.z)
        if not all(math.isfinite(value) for value in values):
            self.web_state=None;self.latest_manual_cmd=None;return
        if any(abs(value)>1e-6 for value in (msg.linear.z,msg.angular.x,msg.angular.y)):
            self.web_state=None;self.latest_manual_cmd=None;return
        if all(abs(value)<1e-6 for value in values):
            self.web_state=None
            self.latest_manual_cmd=None
            self.web_status='已停车'
            return
        vx,vy,wz=values
        if abs(vx)>.801 or abs(vy)>.801 or abs(wz)>1.601:
            self.web_state=None;self.latest_manual_cmd=None;return
        directions=[]
        if abs(vx)>1e-6: directions.append('forward' if vx>0 else 'back')
        if abs(vy)>1e-6: directions.append('left' if vy>0 else 'right')
        if abs(wz)>1e-6: directions.append('turn_left' if wz>0 else 'turn_right')
        self.web_state=(msg,tuple(directions),time.monotonic())
        if self.nav_allowed:
            self.nav_reason='web manual takeover'
            self.cancel_navigation()
        if self.follow_allowed:
            self.follow_allowed=False
            self.follow_cmd=None
            self.latest_nav_cmd=None
            self.get_logger().warn('Follow cancelled: web manual takeover')

    def scan_input(self,topic,msg):
        age=(self.get_clock().now().nanoseconds-msg.header.stamp.sec*10**9-msg.header.stamp.nanosec)/1e9
        if -.1<age<.5 and any(math.isfinite(x) and msg.range_min<x<msg.range_max for x in msg.ranges):
            self.scan_points[topic]=nearby_points(msg,SENSORS[topic])
            self.scan_times[topic]=time.monotonic()

    def navigation_ready(self):
        now=time.monotonic()
        self.nav_reason='ready'
        if self.held or now-self.feedback_at>.5:
            self.nav_reason=f'LB={self.held}, encoder_age={now-self.feedback_at:.3f}'
            return False
        if any(now-self.scan_times.get(t,0)>.5 for t in ('/scan','/scan_low_filtered')):
            self.nav_reason='scan ages: '+str({t:round(now-self.scan_times.get(t,0),3) for t in ('/scan','/scan_low_filtered')})
            return False
        try:
            tf=self.tf_buffer.lookup_transform('map','base_link',rclpy.time.Time())
            age=(self.get_clock().now().nanoseconds-tf.header.stamp.sec*10**9-tf.header.stamp.nanosec)/1e9
            self.nav_reason=f'TF age={age:.3f}'
            return -.5<age<.6
        except Exception as exc:
            self.nav_reason='TF: '+str(exc)
            return False

    def follow_ready(self):
        now=time.monotonic()
        self.follow_reason='ready'
        if self.held or now-self.feedback_at>.5:
            self.follow_reason=f'LB={self.held}, encoder_age={now-self.feedback_at:.3f}'
            return False
        if any(now-self.scan_times.get(t,0)>.5 for t in ('/scan','/scan_low_filtered')):
            self.follow_reason='scan ages: '+str({t:round(now-self.scan_times.get(t,0),3) for t in ('/scan','/scan_low_filtered')})
            return False
        return True

    def cancel_navigation(self):
        if self.nav_allowed:self.get_logger().warn('Navigation cancelled: '+getattr(self,'nav_reason','manual/stop request'))
        self.nav_allowed=False
        self.latest_nav_cmd=None
        if self.nav_cancel.service_is_ready():self.nav_cancel.call_async(CancelGoal.Request())

    def enable_navigation(self,request,response):
        self.latest_nav_cmd=None
        if not request.data:
            self.cancel_navigation();response.success=True
        else:
            self.nav_allowed=not self.follow_allowed and self.navigation_ready()
            self.nav_bad_since=None
            response.success=self.nav_allowed
        response.message='导航已允许' if self.nav_allowed else ('导航已停止' if not request.data else '导航未就绪: '+self.nav_reason)
        return response

    def enable_follow(self,request,response):
        self.follow_cmd=None
        self.latest_nav_cmd=None
        if not request.data:
            self.follow_allowed=False
            response.success=True
            response.message='跟随已停止'
        else:
            # Navigation and person-following share one motor command lane.
            # The documented startup sequence enables navigation permission
            # first, then enables following; selecting follow must atomically
            # leave navigation mode instead of rejecting that sequence.
            if self.nav_allowed:
                self.cancel_navigation()
            self.follow_allowed=self.follow_ready()
            self.follow_at=time.monotonic()
            response.success=self.follow_allowed
            response.message='跟随已允许' if self.follow_allowed else '跟随未就绪: '+self.follow_reason
        return response

    def on_follow_cmd_vel(self,msg):
        if self.follow_allowed and not self.motion_paused:
            msg=copy.deepcopy(msg)
            msg.linear.x=max(-.12,min(.40,msg.linear.x))
            msg.linear.y=0.
            msg.angular.z=max(-.50,min(.50,msg.angular.z))
            points=[p for topic in SENSORS for p in self.scan_points.get(topic,())]
            if follow_motion_blocked(points,msg.linear.x,msg.angular.z):
                msg.linear.x=0.
                msg.angular.z=0.
            self.follow_cmd=msg
            self.follow_at=time.monotonic()

    def joy_input(self,msg):
        self.joy_at=time.monotonic()
        self.held=len(msg.buttons)>4 and bool(msg.buttons[4])
        if self.held and self.nav_allowed:
            self.nav_reason='LB manual takeover'
            self.cancel_navigation()
        if self.held and self.follow_allowed:
            self.follow_allowed=False
            self.follow_cmd=None
            self.latest_nav_cmd=None
            self.get_logger().warn('Follow cancelled: LB manual takeover')
        if not self.held and len(msg.axes)>3 and all(abs(msg.axes[i])<.1 for i in (0,1,3)):
            self.armed=True

    def on_manual_cmd_vel(self,msg):
        self.cmd_at=time.monotonic()
        super().on_manual_cmd_vel(msg)

    def on_nav_cmd_vel(self,msg):
        if self.nav_allowed:
            # Final ceiling after the heading guard, matching the NX Nav2 limits.
            msg=copy.deepcopy(msg)
            msg.linear.x=max(-.20,min(.40,msg.linear.x))
            msg.linear.y=max(-.42,min(.42,msg.linear.y))
            msg.angular.z=max(-1.60,min(1.60,msg.angular.z))
            # Stop only motion *towards* a close frontal obstacle. A polygon
            # STOP in collision_monitor also suppressed safe reverse escape.
            if msg.linear.x>0.:
                points=[p for topic in SENSORS for p in self.scan_points.get(topic,())]
                if blocked('forward',points,msg.linear.x):
                    msg.linear.x=0.
                    msg.linear.y=0.
                    msg.angular.z=0.
            self.nav_at=time.monotonic()
            super().on_nav_cmd_vel(msg)
        elif self.follow_allowed:
            # Official person-following sends its tracking goal through Nav2;
            # collision_monitor publishes the resulting safe twist on this
            # same nav input. Accept it in follow mode with the tighter
            # person-following limits, and feed the normal follow watchdog.
            msg=copy.deepcopy(msg)
            msg.linear.x=max(-.12,min(.40,msg.linear.x))
            msg.linear.y=0.
            msg.angular.z=max(-.50,min(.50,msg.angular.z))
            points=[p for topic in SENSORS for p in self.scan_points.get(topic,())]
            if follow_motion_blocked(points,msg.linear.x,msg.angular.z):
                msg.linear.x=0.
                msg.angular.z=0.
            self.follow_cmd=msg
            self.follow_at=time.monotonic()

    def web_motion_blocked(self,web_state):
        command,directions,_=web_state
        points=[p for topic in SENSORS for p in self.scan_points.get(topic,())]
        for direction in directions:
            speed=(abs(command.angular.z) if direction.startswith('turn') else
                   abs(command.linear.y) if direction in ('left','right') else
                   abs(command.linear.x))
            if blocked(direction,points,speed):return True
        return False

    def _ensure_bus(self):
        ok=super()._ensure_bus()
        if ok: self.bus._serial.write_timeout=.15
        return ok

    def on_command_timer(self):
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
        super().on_command_timer()
        address=os.environ.get('NOTIFY_SOCKET')
        if address:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
                sock.sendto(b'WATCHDOG=1', '\0'+address[1:] if address.startswith('@') else address)

    def publish_command_integrated_odom(self,*args):
        # Do not turn failed encoder reads into apparently measured movement.
        self.feedback_at=0.

    def on_feedback_cycle(self, feedback_by_corner):
        if self.bus is not None and not self.last_feedback_error and not self.last_send_error:
            if feedback_by_corner and all(f.valid for f in feedback_by_corner.values()):
                self.feedback_at=time.monotonic()

    def checkpoint(self):
        tmp=STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(dict(x=self.odom.x,y=self.odom.y,yaw=self.odom.yaw)))
        tmp.replace(STATE)

def main():
    rclpy.init(); node=ManualBase()
    address=os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sock:
            sock.sendto(b'READY=1', '\0'+address[1:] if address.startswith('@') else address)
    executor=MultiThreadedExecutor(num_threads=5)
    executor.add_node(node)
    try: executor.spin()
    except KeyboardInterrupt: pass
    finally:
        executor.shutdown()
        node.checkpoint()
        node.destroy_node()
        rclpy.try_shutdown()

if __name__=='__main__': main()
