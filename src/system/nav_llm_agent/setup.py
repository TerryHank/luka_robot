from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'nav_llm_agent'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'CAPABILITY_GUIDE.md']),
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*.launch.py'))),
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
        (os.path.join('share', package_name, 'scripts'),
            glob(os.path.join('scripts', '*.sh'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yuxi',
    maintainer_email='yuxi@todo.todo',
    description='Luka L4 interaction gateway, voice runtime and L3 agent integration.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'agent_node = nav_llm_agent.agent_node:main',
            'voice_gateway = nav_llm_agent.voice_gateway:main',
            'voice_suite_bridge = nav_llm_agent.voice_suite_bridge:main',
            'interaction_gateway = nav_llm_agent.interaction.agent_gateway:main',
            'interaction_status = nav_llm_agent.interaction.platform_status:main',
            'waypoint_overlay = nav_llm_agent.waypoint_overlay:main',
            'save_waypoint = nav_llm_agent.save_waypoint:main',
        ],
    },
)
