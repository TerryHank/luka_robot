from pathlib import Path
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node
def generate_launch_description():
    return LaunchDescription([
        *([ExecuteProcess(cmd=['python3','/home/sunrise/luka_ws/src/system/runtime/tools/nx_readonly_odom.py'],output='screen')] if not Path('/home/sunrise/luka_ws/src/common/config/nx_manual_mode').exists() else []),
        Node(package='nav2_map_server',executable='map_server',name='map_server',parameters=[{'yaml_filename':'/home/sunrise/luka_data/maps/ddsm_map_floor_4.yaml','use_sim_time':False}],output='screen'),
        Node(package='nav2_amcl',executable='amcl',name='amcl',parameters=['/home/sunrise/luka_ws/src/control/ddsm_car_control/config/nav2_mecanum_mppi_params.yaml',{'set_initial_pose':False}],output='screen'),
        Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',name='nx_localization_manager',parameters=[{'autostart':True,'node_names':['map_server','amcl']}],output='screen')])
