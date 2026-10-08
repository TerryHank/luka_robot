import json,time,urllib.request
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from ai_msgs.msg import PerceptionTargets
from rclpy.action import get_action_client_names_and_types_by_node
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
rclpy.init();node=Node("live_follow_acceptance");statuses=[];targets=[]
tf=Buffer();listener=TransformListener(tf,node)
node.create_subscription(String,"/luka_person_following/adapter_status",lambda m:statuses.append(json.loads(m.data)),10)
node.create_subscription(PerceptionTargets,"/luka/selected_seg_targets",targets.append,10)
end=time.monotonic()+4
while time.monotonic()<end:rclpy.spin_once(node,timeout_sec=.2)
s=json.load(urllib.request.urlopen("http://127.0.0.1:8097/api/people/status"));s.pop("frame_jpeg_base64",None)
result={"monitor":{k:s.get(k) for k in ["active","camera_age","fps","error","person_detector","metric_depth_available","selected_track_id"]},"adapter":statuses[-1] if statuses else None,"target_message_count":len(targets),"target_counts":[len(t.targets) for t in targets],"real_cmd_vel_publishers":[{"name":p.node_name,"namespace":p.node_namespace} for p in node.get_publishers_info_by_topic("/cmd_vel")],"official_action_clients":get_action_client_names_and_types_by_node(node,"tros_person_following_node","/luka_person_following/official")}
assert result["monitor"]["active"] and result["monitor"]["metric_depth_available"] and result["monitor"]["error"] is None
assert result["monitor"]["person_detector"]["depth_method"]=="seg_valid_arithmetic_mean"
assert statuses and statuses[-1]["enabled_applied"] is False
assert targets and not any(result["target_counts"])
assert not any(p["namespace"]=="/luka_person_following/official" for p in result["real_cmd_vel_publishers"])
assert result["official_action_clients"][0][0]=="/luka_follow_dryrun/navigate_to_pose"
mount=tf.lookup_transform("base_footprint","camera_link",Time()).transform
assert abs(mount.translation.x)<1e-6 and abs(mount.translation.y)<1e-6 and abs(mount.translation.z-.7)<1e-6
assert abs(mount.rotation.x)+abs(mount.rotation.y)+abs(mount.rotation.z)<1e-6 and abs(mount.rotation.w-1)<1e-6
result["camera_mount"]={"parent":"base_footprint","child":"camera_link","xyz_m":[mount.translation.x,mount.translation.y,mount.translation.z],"level_forward":True}
result["pass"]=True
from pathlib import Path
Path("/home/sunrise/luka_ws/evaluator/official_follow_acceptance_20261004/live_results.json").write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2));node.destroy_node();rclpy.shutdown()
