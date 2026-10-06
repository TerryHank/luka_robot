from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'start_hobot_xlm', default_value='false',
            choices=['true', 'false']),
        DeclareLaunchArgument(
            'start_hobot_llamacpp', default_value='false',
            choices=['true', 'false']),
        DeclareLaunchArgument(
            'xlm_model_name',
            default_value='DeepSeek_R1_Distill_Qwen_1.5B'),
        DeclareLaunchArgument(
            'llamacpp_model_name',
            default_value='Qwen2.5-0.5B-Instruct-Q4_0.gguf'),

        Node(
            package='hobot_xlm',
            executable='hobot_xlm',
            name='luka_hobot_xlm',
            output='screen',
            condition=IfCondition(LaunchConfiguration('start_hobot_xlm')),
            parameters=[{
                'feed_type': 1,
                'model_name': LaunchConfiguration('xlm_model_name'),
                'ros_string_sub_topic_name': '/luka/llm/xlm/prompt',
                'ai_msg_pub_topic_name': '/luka/llm/xlm/final',
                # Prevent the runtime's intermediate tokens from feeding TTS
                # directly. Luka decides what may be spoken.
                'text_msg_pub_topic_name': '/luka/llm/xlm/stream',
            }]),

        Node(
            package='hobot_llamacpp',
            executable='hobot_llamacpp',
            name='luka_hobot_llamacpp',
            output='screen',
            condition=IfCondition(LaunchConfiguration('start_hobot_llamacpp')),
            parameters=[{
                'feed_type': 2,
                'llm_model_name': LaunchConfiguration('llamacpp_model_name'),
                'system_prompt': 'You are a helpful assistant.',
                'ros_string_sub_topic_name': '/luka/llm/llamacpp/prompt',
                'ai_msg_pub_topic_name': '/luka/llm/llamacpp/final',
                'text_msg_pub_topic_name': '/luka/llm/llamacpp/stream',
            }]),
    ])
