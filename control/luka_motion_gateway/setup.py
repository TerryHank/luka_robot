from setuptools import setup, find_packages

setup(name='luka_motion_gateway', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_motion_gateway"]),
                  ("share/luka_motion_gateway", ["package.xml"])],
      install_requires=["setuptools"],
      entry_points={"console_scripts": ['motion_gateway = luka_motion_gateway.node:main']})
