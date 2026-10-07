from launch_ros.actions import Node
from .paths import workspace_root


def navigation_actions():
 root=workspace_root();params=str(root/'common/config/nx_nav2.yaml')
 specs=[('nav2_controller','controller_server'),('nav2_planner','planner_server'),
        ('nav2_smoother','smoother_server'),('nav2_behaviors','behavior_server'),
        ('nav2_bt_navigator','bt_navigator'),('nav2_velocity_smoother','velocity_smoother')]
 nodes=[]
 for package,name in specs:
  remap=[]
  if name in ('controller_server','behavior_server'):remap=[('cmd_vel','/nx/nav_raw')]
  if name=='velocity_smoother':remap=[('cmd_vel','/nx/nav_raw'),('cmd_vel_smoothed','/luka/motion/nav')]
  nodes.append(Node(package=package,executable=name,name=name,parameters=[params],remappings=remap,output='screen'))
 nodes.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='nx_navigation_manager',
              parameters=[{'autostart':True,'node_names':[name for _,name in specs],'bond_timeout':4.0}],output='screen'))
 return nodes


def safety_actions():
 root=workspace_root()
 return [Node(package='luka_motion_gateway',executable='motion_gateway',output='screen'),
         Node(package='ddsm_car_control',executable='ddsm_lateral_escape_guard',name='lateral_escape_guard',
              parameters=[str(root/'common/config/nx_heading_guard.yaml')],output='screen'),
         Node(package='nav2_collision_monitor',executable='collision_monitor',name='collision_monitor',
              parameters=[str(root/'common/config/nx_nav2.yaml')],output='screen'),
         Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='nx_safety_manager',
              parameters=[{'autostart':True,'node_names':['collision_monitor'],'bond_timeout':4.0}],output='screen')]
