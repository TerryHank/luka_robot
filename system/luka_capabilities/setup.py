from setuptools import setup, find_packages

setup(name='luka_capabilities', version="0.1.0", packages=find_packages(),
      data_files=[("share/ament_index/resource_index/packages", ["resource/luka_capabilities"]),
                  ("share/luka_capabilities", ["package.xml"])],
      install_requires=["setuptools"],
      entry_points={"console_scripts": []})
