from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    params='/home/sunrise/luka_ws/common/config/nx_nav2.yaml'
    specs=[('nav2_controller','controller_server'),('nav2_planner','planner_server'),
           ('nav2_smoother','smoother_server'),('nav2_behaviors','behavior_server'),
           ('nav2_bt_navigator','bt_navigator'),('nav2_velocity_smoother','velocity_smoother'),
           ('nav2_collision_monitor','collision_monitor')]
    nodes=[]
    nodes.append(Node(package='ddsm_car_control',executable='ddsm_lateral_escape_guard',name='lateral_escape_guard',parameters=['/home/sunrise/luka_ws/common/config/nx_heading_guard.yaml'],output='screen'))
    for package,name in specs:
        remap=[]
        if name in ('controller_server','behavior_server'):remap=[('cmd_vel','/nx/nav_raw')]
        if name=='velocity_smoother':remap=[('cmd_vel','/nx/nav_raw'),('cmd_vel_smoothed','/nx/nav_smoothed')]
        nodes.append(Node(package=package,executable=name,name=name,parameters=[params],remappings=remap,output='screen'))
    nodes.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='nx_navigation_manager',parameters=[{'autostart':True,'node_names':[n for _,n in specs],'bond_timeout':4.0}],output='screen'))
    return LaunchDescription(nodes)
