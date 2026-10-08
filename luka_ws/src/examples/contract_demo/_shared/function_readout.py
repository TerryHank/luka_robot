"""Read live ROS results; no velocity, goal or business-command publishers."""
import argparse
import math
import struct
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from sensor_msgs.msg import Image, LaserScan, Imu
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from nav2_msgs.msg import CollisionMonitorState
from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
from std_msgs.msg import String

SENSOR = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
SPECS = {
    "lidar": [(LaserScan,t) for t in ("/scan","/scan_low_filtered","/scan_obstacle_fused","/contract_demo/scan_deskewed")],
    "camera": [(Image,t) for t in ("/camera/color/image_raw","/camera/depth/image_raw")],
    "interfaces": [(Odometry,"/wheel/odom"),(Imu,"/imu/data"),(String,"/hotel/mission/status")],
    "slam": [(OccupancyGrid,"/map"),(Odometry,"/wheel/odom")],
    "map": [(OccupancyGrid,"/map")],
    "localization": [(PoseWithCovarianceStamped,"/amcl_pose"),(Odometry,"/wheel/odom")],
    "navigation": [(Path,"/plan"),(String,"/hotel/navigation_status")],
    "avoidance": [(LaserScan,"/scan_obstacle_fused"),(CollisionMonitorState,"/collision_monitor_state"),(String,"/nx/web_teleop_status"),(String,"/hotel/navigation_status")],
    "smoothing": [(Twist,t) for t in ("/nx/nav_raw","/nx/nav_smoothed","/nx/nav_guarded","/nx/nav_safe")],
    "business": [(String,t) for t in ("/patrol/status","/home/status","/hotel/mission/status")]+[(Path,"/patrol/route_path")],
    "home": [(String,"/home/status")],
    "state_machine": [(String,t) for t in ("/hotel/mission/status","/hotel/mission/safety_status","/hotel/mission/goal_status")],
    "voice": [(String,t) for t in ("/voice/doa","/voice/status","/voice/recognized_text","/llm_voice_command","/llm_status")],
    "face": [(Image,"/contract_demo/face_image")],
    "diagnostics": [(String,t) for t in ("/nx/web_teleop_status","/hotel/mission/safety_status")],
}
SPECS["layers"] = SPECS["interfaces"] + [(LaserScan,"/scan"),(OccupancyGrid,"/map"),(Path,"/plan")]


def describe(m):
    if isinstance(m, LaserScan):
        valid = [v for v in m.ranges if math.isfinite(v) and m.range_min <= v <= m.range_max]
        return "rays=%d valid=%d nearest=%s m" % (len(m.ranges),len(valid),
                 "%.3f" % min(valid) if valid else "NONE")
    if isinstance(m, Image):
        value = ""
        if m.encoding in ("16UC1","32FC1") and m.width and m.height:
            width = 2 if m.encoding == "16UC1" else 4
            offset = (m.height//2)*m.step+(m.width//2)*width
            if len(m.data) >= offset+width:
                depth = struct.unpack_from((">" if m.is_bigendian else "<")+
                                           ("H" if width==2 else "f"), bytes(m.data), offset)[0]
                if width==2: depth /= 1000.
                value = " center_depth=%s m" % ("%.3f"%depth if math.isfinite(depth) and depth>0 else "INVALID")
        return "%dx%d %s%s" % (m.width,m.height,m.encoding,value)
    if isinstance(m, OccupancyGrid):
        known = sum(v>=0 for v in m.data)
        return "map=%dx%d resolution=%.3f m known_cells=%d" % (m.info.width,m.info.height,m.info.resolution,known)
    if isinstance(m, Path):
        return "waypoints=%d frame=%s" % (len(m.poses),m.header.frame_id)
    if isinstance(m, (Odometry,PoseWithCovarianceStamped)):
        p=m.pose.pose.position
        return "x=%.4f y=%.4f m" % (p.x,p.y)
    if isinstance(m, Imu):
        a,w=m.linear_acceleration,m.angular_velocity
        return "a=(%.3f,%.3f,%.3f)m/s² gyro=(%.3f,%.3f,%.3f)rad/s" % (a.x,a.y,a.z,w.x,w.y,w.z)
    if isinstance(m, Twist):
        return "vx=%.3f vy=%.3f m/s wz=%.3f rad/s" % (m.linear.x,m.linear.y,m.angular.z)
    if isinstance(m, CollisionMonitorState):
        return "action_type=%d polygon=%s" % (m.action_type,m.polygon_name)
    return m.data[:800]


class Readout(Node):
    def __init__(self, profile):
        super().__init__("contract_demo_"+profile+"_readout")
        self.profile,self.values,self.graph_tick=profile,{},0
        for kind, topic in SPECS[profile]:
            qos=LATCHED if kind is OccupancyGrid else SENSOR
            self.create_subscription(kind,topic,lambda m,t=topic:self.receive(t,m),qos)
        self.create_timer(1.,self.report)

    def receive(self,topic,message):
        stamp=None
        if hasattr(message,"header"):
            stamp=message.header.stamp.sec+message.header.stamp.nanosec/1e9
        self.values[topic]=(time.monotonic(),stamp,describe(message))

    def report(self):
        for _,topic in SPECS[self.profile]:
            if topic not in self.values:
                print("[WAITING]",topic,"no real message",flush=True)
                continue
            arrival,stamp,value=self.values[topic]
            static=topic in ("/map","/plan","/patrol/route_path")
            age=self.get_clock().now().nanoseconds/1e9-stamp if stamp is not None else time.monotonic()-arrival
            valid=(stamp is None or stamp>0) and (static or -.1<=age<=2.)
            label="STATIC/EVENT" if static and valid else "LIVE" if valid else "STALE/INVALID"
            print("[%s] %s age=%.2fs %s"%(label,topic,age,value),flush=True)
        self.graph_tick+=1
        if self.profile in ("layers","interfaces","diagnostics") and self.graph_tick%5==1:
            graph=sorted(n if ns=="/" else ns.rstrip("/")+"/"+n
                         for n,ns in self.get_node_names_and_namespaces())
            print("[GRAPH]",", ".join(graph),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--profile",choices=tuple(SPECS),required=True)
    args,ros=p.parse_known_args()
    rclpy.init(args=ros)
    node=Readout(args.profile)
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__=="__main__":main()