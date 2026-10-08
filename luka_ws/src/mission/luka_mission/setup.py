from setuptools import setup, find_packages

setup(name='luka_mission', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_mission"]),
                  ("share/luka_mission", ["package.xml"])],
      install_requires=["setuptools"],
      entry_points={"console_scripts": []})
