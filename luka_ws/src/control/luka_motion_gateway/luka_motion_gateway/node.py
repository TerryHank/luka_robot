import json
import threading
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Joy
from std_msgs.msg import String, Empty

from .arbiter import MotionArbiter
from .sources import INPUT_TOPICS, OUTPUT_TOPIC


class MotionGateway(Node):
    def __init__(self):
        super().__init__('luka_motion_gateway');self.arbiter=MotionArbiter();self.lock=threading.RLock();self.ack={}
        self.base_state={};self.base_received=0.
        self.velocity=self.create_publisher(Twist,OUTPUT_TOPIC,1)
        self.state=self.create_publisher(String,'/luka/motion/status',1)
        for source,topic in INPUT_TOPICS.items():
            self.create_subscription(Twist,topic,lambda msg,s=source:self.receive(s,msg),1)
        self.create_subscription(String,'/luka/motion/lease',self.request,10)
        self.create_subscription(Empty,'/luka/motion/stop',lambda _:self.stop(),10)
        self.create_subscription(Joy,'/joy',self.joy,10)
        self.create_subscription(Twist,'/nx/web_teleop_cmd_vel',self.manual,1)
        self.create_subscription(String,'/luka/base/status',self.base_status,10)
        self.create_timer(.05,self.tick)

    def receive(self,source,msg):
        with self.lock:self.arbiter.receive(source,[msg.linear.x,msg.linear.y,msg.linear.z,msg.angular.x,msg.angular.y,msg.angular.z])

    def request(self,msg):
        with self.lock:
            command={}
            try:
                if len(msg.data)>2048:raise ValueError('lease request too large')
                payload=json.loads(msg.data)
                if not isinstance(payload,dict):raise ValueError('lease request must be an object')
                command=payload
                if command.get('mode')!='release' and not self.base_ready():raise ValueError('base safety gate unavailable or stale')
                self.arbiter.lease.request(command)
                self.ack={'request_id':command.get('request_id'),'accepted':True,'error':''}
            except Exception as error:
                self.ack={'request_id':command.get('request_id'),'accepted':False,'error':str(error)}
            self.tick()

    def joy(self,msg):
        with self.lock:self.arbiter.lease.manual_input('joystick',len(msg.buttons)>4 and bool(msg.buttons[4]))
        self.tick()

    def manual(self,msg):
        with self.lock:self.arbiter.lease.manual_input('web',any(abs(v)>1e-6 for v in (msg.linear.x,msg.linear.y,msg.angular.z)))
        self.tick()

    def stop(self):
        with self.lock:self.arbiter.stop();self.tick()

    def base_ready(self):
        return time.monotonic()-self.base_received<=.6 and self.base_state.get('healthy') is True

    def base_status(self,msg):
        try:state=json.loads(msg.data)
        except (ValueError,TypeError):return
        if not isinstance(state,dict):return
        with self.lock:
            self.base_state=state;self.base_received=time.monotonic()
            self.arbiter.lease.manual_input('base',bool(state.get('manual_active')))

    def tick(self):
        with self.lock:
            if not self.base_ready() and self.arbiter.lease.source:self.arbiter.stop('base safety heartbeat expired or unhealthy')
            values=self.arbiter.output();msg=Twist()
            msg.linear.x,msg.linear.y,msg.linear.z,msg.angular.x,msg.angular.y,msg.angular.z=values
            self.velocity.publish(msg)
            self.state.publish(String(data=json.dumps(dict(self.arbiter.status(),ack=self.ack),allow_nan=False)))


def main():
    rclpy.init();node=MotionGateway()
    try:rclpy.spin(node)
    except (KeyboardInterrupt,ExternalShutdownException):pass
    except RuntimeError:
        if rclpy.ok():raise
    finally:
        if rclpy.ok():node.stop()
        else:node.arbiter.stop('gateway shutting down')
        node.destroy_node();rclpy.try_shutdown()
