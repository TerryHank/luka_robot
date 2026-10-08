"""Narrow mask for the user-confirmed low-lidar chassis bracket; not a range cutoff."""
import copy,math,sys
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data

def bracket_point(r,angle):
    if not math.isfinite(r): return False
    x=.281+r*math.cos(angle+1.56975)
    y=.005+r*math.sin(angle+1.56975)
    # Front-left bracket envelope, wholly inside the configured vehicle hull.
    # Covers repeat observations while stationary and turning, plus inward margin.
    return .280<=x<=.390 and .100<=y<=.230

class ChassisFilter(Node):
    def __init__(self):
        super().__init__('nx_chassis_bracket_filter')
        self.pub=self.create_publisher(LaserScan,'/scan_low_chassis_filtered',qos_profile_sensor_data)
        self.create_subscription(LaserScan,'/scan_low_raw',self.receive,qos_profile_sensor_data)
    def receive(self,msg):
        if msg.header.frame_id!='laser_low':
            self.get_logger().error('Unexpected low lidar frame; withholding scan')
            return
        out=copy.deepcopy(msg)
        out.ranges=[float('inf') if bracket_point(r,msg.angle_min+i*msg.angle_increment) else r for i,r in enumerate(msg.ranges)]
        self.pub.publish(out)

if __name__=='__main__':
    rclpy.init();node=ChassisFilter()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:node.destroy_node();rclpy.try_shutdown()
