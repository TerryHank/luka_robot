from launch import LaunchDescription
from launch.actions import ExecuteProcess,SetEnvironmentVariable
from luka_bringup.paths import workspace_root

def generate_launch_description():
 root=workspace_root()
 return LaunchDescription([
   SetEnvironmentVariable('NX_PERSON_ROS_PUBLISH','1'),
   SetEnvironmentVariable('NX_PERSON_DETECTOR','yolo26_seg'),
   SetEnvironmentVariable('NX_PEOPLE_CAMERA','stereo_shared'),
   ExecuteProcess(cmd=['/bin/bash',str(root/'system/scripts/start_orbbec_camera.sh')],output='screen'),
   ExecuteProcess(cmd=['/bin/bash',str(root/'system/scripts/start_orbbec_vision.sh')],output='screen'),
   ExecuteProcess(cmd=[str(root/'perception/person_follow/yolo26_venv/bin/python'),str(root/'common/legacy/s100_object_api.py')],output='screen'),
   ExecuteProcess(cmd=[str(root/'perception/person_follow/yolo26_venv/bin/python'),str(root/'perception/person_follow/server.py')],output='screen'),
   ExecuteProcess(cmd=['python3',str(root/'system/helpers/luka-ws-start-people-worker')],output='screen')])
