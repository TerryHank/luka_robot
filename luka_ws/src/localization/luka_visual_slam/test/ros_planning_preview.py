"""Checks the isolated planner only. No controller or navigation goal is used."""
import json
from pathlib import Path
import time
import rclpy
from rclpy.action import ActionClient
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import OccupancyGrid
from nav2_msgs.action import ComputePathToPose
from geometry_msgs.msg import PoseStamped

rclpy.init();n=rclpy.create_node('visual_slam_planning_probe');maps=[]
n.create_subscription(OccupancyGrid,'/rtabmap_rgbd/global_costmap/costmap',lambda m:maps.append(m) if not maps else None,qos_profile_sensor_data)
end=time.monotonic()+10
while not maps and time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.1)
assert maps,'isolated Nav2 costmap did not receive the RTAB-Map map'
m=maps[-1];free={i for i,v in enumerate(m.data) if v==0}
pair=next(((i,i+3) for i in sorted(free) if i+3 in free and i//m.info.width==(i+3)//m.info.width),None)
assert pair,'no short free-space pair in the stationary preview map'
def pose(index):
 p=PoseStamped();p.header.frame_id=m.header.frame_id;p.header.stamp=n.get_clock().now().to_msg()
 p.pose.position.x=m.info.origin.position.x+(index%m.info.width+.5)*m.info.resolution
 p.pose.position.y=m.info.origin.position.y+(index//m.info.width+.5)*m.info.resolution
 p.pose.orientation.w=1.;return p
client=ActionClient(n,ComputePathToPose,'/rtabmap_rgbd/compute_path_to_pose')
assert client.wait_for_server(timeout_sec=5)
goal=ComputePathToPose.Goal();goal.use_start=True;goal.start=pose(pair[0]);goal.goal=pose(pair[1]);goal.planner_id='GridBased'
future=client.send_goal_async(goal);rclpy.spin_until_future_complete(n,future,timeout_sec=10)
assert future.done() and future.result().accepted
future=future.result().get_result_async();rclpy.spin_until_future_complete(n,future,timeout_sec=10)
assert future.done()
response=future.result()
result={'action':'/rtabmap_rgbd/compute_path_to_pose','status':response.status,
        'path_poses':len(response.result.path.poses),'map_frame':m.header.frame_id,
        'cmd_vel_publishers':[p.node_namespace+'/'+p.node_name for p in n.get_publishers_info_by_topic('/cmd_vel')],
        'motion_sent':False}
assert response.status==4 and result['path_poses']>=2,result
out=Path('/home/sunrise/luka_ws/log/visual_slam');out.mkdir(parents=True,exist_ok=True)
(out/'planning_preview.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
n.destroy_node();rclpy.shutdown()
