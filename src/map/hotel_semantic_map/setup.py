from glob import glob

from setuptools import find_packages, setup


package_name = "hotel_semantic_map"


setup(
    name=package_name,
    version="0.0.1",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", glob("config/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="maintainer",
    maintainer_email="maintainer@example.com",
    description="Versioned hotel semantic areas, named destinations, and ROS query services.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "named_navigation_server = hotel_semantic_map.named_navigation_server:main",
            "semantic_map_server = hotel_semantic_map.semantic_map_server:main",
        ],
    },
)
