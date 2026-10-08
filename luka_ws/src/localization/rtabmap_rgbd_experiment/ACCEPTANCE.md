# RGB-D trial acceptance — 2026-10-08

PASS: stationary live Astra Pro Plus RGB-D initialization, ROS odometry, map cloud and occupancy output.

Core source was cloned but not compiled; official ROS Humble RTAB-Map 0.23.7 binaries were exercised.
Camera input: 640x480 RGB8 and registered 16UC1 depth, approximately 30 Hz, matching color intrinsics and optical frame.

```json
{
  "started": 1791458650.9852936,
  "odom_count": 569,
  "finite_odom_count": 569,
  "map_nodes": 2,
  "cloud_points": 2809,
  "map_cells": 8500,
  "experimental_tf_messages": 0,
  "private_tf_messages": 1136,
  "max_odom_age_s": 0.14617204666137695,
  "odom_frame": "rtabmap_rgbd_odom",
  "odom_child": "camera_link",
  "cloud_frame": "rtabmap_rgbd_map",
  "production_publishers": {
    "/map": [],
    "/odom": [],
    "/cmd_vel": []
  },
  "pass_stationary_initialization": true,
  "moving_mapping_and_loop_closure": "not tested",
  "database": "/home/sunrise/luka_data/maps/rtabmap_rgbd/20261008_192410_453885330/map.db",
  "database_quick_check": "ok",
  "database_nodes": 92,
  "database_bytes": 37531648,
  "cloud_ply": "/home/sunrise/luka_data/maps/rtabmap_rgbd/20261008_192410_453885330/cloud_xyz.ply"
}
```

Final trial stopped cleanly; RTAB-Map logged successful database and occupancy-grid save.
Initial trial exposed missing odometry TF: resolved by remapping both experiment nodes to private /rtabmap_rgbd/tf.
Bounded systemd trials should use KillMode=mixed and KillSignal=SIGINT so ros2 launch coordinates child shutdown.
No motion command was sent. Existing navigation/SLAM launch and configuration files were not edited.
Production navigation was inactive before and after this test; concurrent production SLAM was not live-tested.
Moving mapping, loop closure, database relocalization and room-scale accuracy remain untested.
Root layout and package uniqueness checks passed: 24 distinct source package names; 12 functional owner entries.
