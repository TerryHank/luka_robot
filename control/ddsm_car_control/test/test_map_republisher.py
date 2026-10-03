from builtin_interfaces.msg import Time
from nav_msgs.msg import OccupancyGrid

from ddsm_car_control.map_republisher import (
    OccupancyGridRepublisher,
    refresh_occupancy_grid_stamp,
)


def test_refresh_occupancy_grid_stamp_preserves_map_content_and_updates_stamp():
    grid = OccupancyGrid()
    grid.header.frame_id = "map"
    grid.header.stamp.sec = 1
    grid.header.stamp.nanosec = 2
    grid.info.resolution = 0.05
    grid.info.width = 2
    grid.info.height = 2
    grid.data = [0, 100, -1, 50]

    refreshed = refresh_occupancy_grid_stamp(grid, Time(sec=9, nanosec=10))

    assert refreshed.header.frame_id == "map"
    assert refreshed.header.stamp.sec == 9
    assert refreshed.header.stamp.nanosec == 10
    assert refreshed.info.resolution == 0.05
    assert refreshed.info.width == 2
    assert refreshed.info.height == 2
    assert list(refreshed.data) == [0, 100, -1, 50]
    assert grid.header.stamp.sec == 1


def test_on_map_caches_latest_map_without_bypassing_publish_frequency():
    grid = OccupancyGrid()

    node = OccupancyGridRepublisher.__new__(OccupancyGridRepublisher)
    node.latest_map = None
    publish_calls = []
    node.publish_latest_map = lambda: publish_calls.append("published")

    OccupancyGridRepublisher.on_map(node, grid)

    assert node.latest_map is grid
    assert publish_calls == []


def test_ddsm_slam_launch_republishes_slam_map_to_public_map():
    launch_text = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("launch", "ddsm_slam.launch.py")
        .read_text(encoding="utf-8")
    )
    setup_text = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("setup.py")
        .read_text(encoding="utf-8")
    )

    assert 'SetRemap(src="/map", dst="/slam_map")' in launch_text
    assert "executable=\"map_republisher\"" in launch_text
    assert "input_topic" in launch_text
    assert "output_topic" in launch_text
    assert "ekf_params_file_arg" in launch_text
    assert '"ekf_params_file": LaunchConfiguration("ekf_params_file")' in launch_text
    assert "map_republisher = ddsm_car_control.map_republisher:main" in setup_text
