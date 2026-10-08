from launch import LaunchDescription
from launch_ros.actions import Node
from luka_bringup.paths import workspace_root

def generate_launch_description():
 root=workspace_root()
 # Hardware owns the sole wheel-odom/serial node; no readonly encoder node here.
 return LaunchDescription([
   Node(package='nav2_map_server',executable='map_server',name='map_server',
        parameters=[{'yaml_filename':str(root/'map/maps/ddsm_map_floor_4.yaml'),'use_sim_time':False}],output='screen'),
   Node(package='nav2_amcl',executable='amcl',name='amcl',
        parameters=[str(root/'control/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml'),{'set_initial_pose':False}],output='screen'),
   Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='nx_localization_manager',
        parameters=[{'autostart':True,'node_names':['map_server','amcl']}],output='screen')])
