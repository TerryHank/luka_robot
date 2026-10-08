from setuptools import setup, find_packages

setup(name='luka_base_gate', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_base_gate"]),
                  ("share/luka_base_gate", ["package.xml"])],
      install_requires=["setuptools"],
      entry_points={"console_scripts": ['base_gate = luka_base_gate.gate:main']})
