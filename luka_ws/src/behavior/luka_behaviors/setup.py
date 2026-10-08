from setuptools import setup, find_packages

setup(name='luka_behaviors', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_behaviors"]),
                  ("share/luka_behaviors", ["package.xml"])],
      install_requires=["setuptools"],
      entry_points={"console_scripts": []})
