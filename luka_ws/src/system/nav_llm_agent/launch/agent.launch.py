from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    from nav_llm_agent.waypoint_store import default_waypoints_path
    default_waypoints = default_waypoints_path()
    default_capabilities = os.path.join(
        get_package_share_directory('nav_llm_agent'), 'config', 'capabilities.yaml')

    waypoint_params = {
        'waypoints_file': LaunchConfiguration('waypoints_file'),
        'use_sim_time': ParameterValue(
            LaunchConfiguration('use_sim_time'), value_type=bool),
    }

    return LaunchDescription([
        DeclareLaunchArgument('waypoints_file', default_value=default_waypoints),
        DeclareLaunchArgument('capabilities_file', default_value=default_capabilities),
        DeclareLaunchArgument('ollama_url', default_value='http://127.0.0.1:8080'),
        DeclareLaunchArgument('model', default_value='qwen2.5-1.5b'),
        DeclareLaunchArgument('llm_api', default_value='openai'),
        # Board/real robot: start_agent.sh passes false; sim can override true.
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('dry_run', default_value='false'),
        Node(
            package='nav_llm_agent',
            executable='agent_node',
            name='nav_llm_agent',
            output='screen',
            parameters=[{
                **waypoint_params,
                'capabilities_file': LaunchConfiguration('capabilities_file'),
                'ollama_url': LaunchConfiguration('ollama_url'),
                'model': LaunchConfiguration('model'),
                'llm_api': LaunchConfiguration('llm_api'),
                'dry_run': ParameterValue(
                    LaunchConfiguration('dry_run'), value_type=bool),
                'temperature': 0.1,
                'num_ctx': 3072,
                'max_tokens': 160,
                'think': False,
            }],
        ),
        Node(
            package='nav_llm_agent',
            executable='waypoint_overlay',
            name='waypoint_overlay',
            output='screen',
            parameters=[waypoint_params],
        ),
    ])
