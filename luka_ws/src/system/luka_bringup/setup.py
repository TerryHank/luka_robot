from setuptools import setup, find_packages
from glob import glob

setup(name='luka_bringup', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_bringup"]),
                  ("share/luka_bringup", ["package.xml"]),
                  ("share/luka_bringup/launch", glob("launch/*.launch.py"))],
      install_requires=["setuptools"],
      entry_points={"console_scripts": ['runtime_host = luka_bringup.runtime_host:main']})
