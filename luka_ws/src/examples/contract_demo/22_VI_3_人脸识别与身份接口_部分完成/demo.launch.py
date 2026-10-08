from pathlib import Path
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    shared = Path(__file__).resolve().parent.parent / "_shared" / "function_demo.launch.py"
    return LaunchDescription([IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(shared)),
        launch_arguments={"profile": "face"}.items())])
