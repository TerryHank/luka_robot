from setuptools import setup
setup(name='luka_person_following', version='0.1.0', packages=['luka_person_following'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/luka_person_following']),
                  ('share/luka_person_following', ['package.xml']),
                  ('share/luka_person_following/launch', ['launch/selected_follow.launch.py']),
                  ('share/luka_person_following/config', ['config/target_relock.yaml'])],
      entry_points={'console_scripts': ['selected_bridge = luka_person_following.bridge:main']})
