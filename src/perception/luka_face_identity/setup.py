from setuptools import setup

setup(name='luka_face_identity', version='0.1.0', packages=['luka_face_identity'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/luka_face_identity']),
                  ('share/luka_face_identity', ['package.xml']),
                  ('share/luka_face_identity/launch', ['launch/face_identity.launch.py'])],
      install_requires=['setuptools'],
      entry_points={'console_scripts': ['face_identity = luka_face_identity.node:main']})
