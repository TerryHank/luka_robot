"""Measured wheel odometry for stationary commissioning; only read requests allowed."""
import math,sys
sys.path.insert(0,'/home/sunrise/luka_ws/control/ddsm_car_control')
import rclpy
from rclpy.node import Node
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
from ddsm_car_control.zdt_y42_protocol import ZDTY42SerialBus
from ddsm_car_control.zdt_mecanum_kinematics import MecanumGeometry,motor_delta_degrees_to_body_delta

class ReadOnlyBus(ZDTY42SerialBus):
    def exchange_free_frame(self,frame,response_len,expected_address,function_code):
        if frame!=bytes([expected_address,0x36,0x6b]) or function_code!=0x36:
            raise RuntimeError('Only position read requests allowed')
        return super().exchange_free_frame(frame,response_len,expected_address,function_code)
    def write(self,*args): raise RuntimeError('Control writes disabled')
    def exchange(self,*args): raise RuntimeError('Control exchange disabled')

class WheelOdom(Node):
    def __init__(self):
        super().__init__('nx_readonly_wheel_odom')
        self.bus=ReadOnlyBus('/dev/nx_base',protocol='free',firmware='x',timeout=.03)
        self.previous=None; self.x=self.y=self.yaw=0.
        self.pub=self.create_publisher(Odometry,'/wheel/odom',10)
        self.tf=TransformBroadcaster(self)
        self.create_timer(.1,self.poll)
    def poll(self):
        try: positions={i:self.bus.read_position_degrees(i) for i in (1,2,3,4)}
        except Exception as exc:
            self.get_logger().error('Encoder read failed; withholding odometry: '+str(exc))
            return
        now=self.get_clock().now()
        if self.previous is None: self.previous=positions; self.last=now
        delta={i:positions[i]-self.previous[i] for i in positions}
        if any(abs(v)>30 for v in delta.values()):
            self.get_logger().error('Large encoder change: stationary validation requires restart')
            return
        dx,dy,da=motor_delta_degrees_to_body_delta(delta,MecanumGeometry())
        dt=max(.001,(now-self.last).nanoseconds/1e9)
        self.x+=math.cos(self.yaw)*dx-math.sin(self.yaw)*dy
        self.y+=math.sin(self.yaw)*dx+math.cos(self.yaw)*dy
        self.yaw+=da; self.previous=positions; self.last=now
        msg=Odometry(); msg.header.stamp=now.to_msg(); msg.header.frame_id='odom'; msg.child_frame_id='base_link'
        msg.pose.pose.position.x=self.x; msg.pose.pose.position.y=self.y
        msg.pose.pose.orientation.z=math.sin(self.yaw/2); msg.pose.pose.orientation.w=math.cos(self.yaw/2)
        msg.twist.twist.linear.x=dx/dt; msg.twist.twist.linear.y=dy/dt; msg.twist.twist.angular.z=da/dt
        for index in (0,7,35): msg.pose.covariance[index]=.02; msg.twist.covariance[index]=.02
        self.pub.publish(msg)
        tf=TransformStamped(); tf.header=msg.header; tf.child_frame_id='base_link'
        tf.transform.translation.x=self.x; tf.transform.translation.y=self.y
        tf.transform.rotation=msg.pose.pose.orientation; self.tf.sendTransform(tf)

def main():
    rclpy.init(); node=WheelOdom()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally: node.bus.close(); node.destroy_node(); rclpy.try_shutdown()
if __name__=='__main__': main()
