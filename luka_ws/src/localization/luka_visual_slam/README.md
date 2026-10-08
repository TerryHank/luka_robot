# Luka visual SLAM — Astra RGB-D adaptation of VIMS

Architecture reference: https://github.com/D-Robotics/tros_vims_doc/blob/main/tros_vims_doc.md
RTAB-Map ROS interfaces: https://github.com/introlab/rtabmap_ros/tree/ros2

```text
sensing: canonical Astra RGB + registered depth + CameraInfo
   ├─ localization frontend: rgbd_odometry ── local odometry ────┐
   └─ perception interface: aligned dynamic mask → depth filter ┤
                                                               ↓
                      RTAB-Map backend: map / loop closure / localization
                                                               ↓
                            optional isolated Nav2 planning preview
```

The Astra supplies depth directly, replacing the stereo-depth branch for this
hardware. Its front end is RGB-D visual odometry, not a stereo/IMU VIO or the
binary drobotics_vio. No StereoNet, IMU calibration or VIO support is claimed.
Core source is pinned separately in `../rtabmap`; installed official Humble
0.23.7 binaries run this integration. No second camera driver is launched.

## Start and stop

```bash
sudo systemctl start luka-ws-orbbec-camera.service
bash ~/luka_ws/src/localization/luka_visual_slam/start.sh
```

Ctrl+C stops the nodes and saves a new `~/luka_data/maps/visual_slam/<session>/map.db`.
Every mapping session is new. Nothing deletes or overwrites existing maps.
At least 1500 MiB available RAM is required. A process lock and a ROS graph check
reject duplicate owners. Logs are in `~/luka_ws/log/visual_slam`.

Localize using a saved RTAB-Map database:

```bash
bash ~/luka_ws/src/localization/luka_visual_slam/start.sh \
  mode:=localization database_path:=/home/sunrise/luka_data/maps/visual_slam/SESSION/map.db
```

Localization works on a SQLite backup under `~/luka_data/runtime/visual_slam/`,
preserving the original map byte-for-byte. Incremental mapping is disabled.

## Optional dynamic depth filtering

```bash
bash ~/luka_ws/src/localization/luka_visual_slam/start.sh \
  mask_depth:=true mask_topic:=/perception/dynamic_mask
```

The mask producer must publish `sensor_msgs/Image`, encoding `mono8`, same
640x480 registered color geometry/optical frame and original acquisition
timestamp. Zero pixels are static; nonzero pixels are excluded from mapping.
Millimeter uint16 depths become zero; float32 meter depths become NaN.
RGB, depth, CameraInfo and mask must be within 60 ms and at most 600 ms old.
Missing, stale or mismatched masks stop filtered output; no raw fallback is used.
Only mapping depth is masked; high-rate visual odometry consumes the original
RGB-D branch. Status: `/rtabmap_rgbd/depth_filter/status`.

A real mask producer is available via `sudo systemctl start luka-ws-dynamic-mask.service`.
It reuses the canonical `luka-ws-object-api` YOLO26 BPU person segmentation model
and the existing camera service. It publishes `/perception/dynamic_mask` with
the original RGB acquisition timestamp; results older than 600 ms are discarded.
Check `/perception/dynamic_mask/status` for `state=publishing` before starting
SLAM with `mask_depth:=true`. This optional service is not enabled at boot.
All detected person regions are masked, including stationary people; other
classes and motion classification are not claimed. Fixed-camera real-person
filtering passed the 2026-10-08 live test; see LIVE_DYNAMIC_ACCEPTANCE.md.
The mask producer owns neither camera acquisition nor another model instance.

## Nav2 interface without changing existing SLAM

```bash
bash ~/luka_ws/src/localization/luka_visual_slam/start.sh planning_preview:=true
```

This starts only an isolated `planner_server`, global costmap and lifecycle
manager. It consumes RTAB-Map's occupancy map and private TF. The footprint,
padding and inflation values are copied from the existing Luka navigation profile.
It exposes `/rtabmap_rgbd/compute_path_to_pose`; no controller, velocity output
or production `/navigate_to_pose` server is started. This preview does not include
live obstacle layers and must not be treated as a complete collision-aware
navigation stack. Production navigation handover is a separate operation.

| Output | Meaning |
|---|---|
| `/rtabmap_rgbd/odom` | RGB-D frontend odometry |
| `/rtabmap_rgbd/tf` | Private map → odom → camera chain |
| `/rtabmap_rgbd/map` | Occupancy grid |
| `/rtabmap_rgbd/cloud_map` | Map point cloud |
| `/rtabmap_rgbd/mapData`, `/rtabmap_rgbd/info` | Backend graph and diagnostics |
| `/rtabmap_rgbd/global_costmap/costmap` | Optional Nav2 map-consuming preview |

Production `/tf`, `/map`, `/odom`, `/cmd_vel`, existing SLAM configurations and
services are not replaced. Existing camera `/tf_static` remains the source for
internal camera transforms. Foxglove fixed frame: `rtabmap_rgbd_map`.

An external frontend can be supplied with `frontend:=external` and
`external_odom_topic:=/your/odom` (`nav_msgs/Odometry`). It must provide calibrated
camera/body transforms; publish the matching odometry transform on the private
TF topic for accurate timestamp interpolation. No unverified VIO is auto-started.
The external frontend is an interface contract, not a live VIO acceptance claim.

## Verification

Build only this adapter with `colcon build --base-paths src --packages-select luka_visual_slam`.
`colcon test --packages-select luka_visual_slam` covers depth units, invalid masks,
timestamps/frames, unique map creation and original-map preservation.
`test/ros_mask_transport.py` tests real ROS transport in isolated domain 189.
`test/ros_planning_preview.py` submits only ComputePathToPose to the private
planner; it never sends a navigation goal or a velocity command.
See ACCEPTANCE.md for actual live results and remaining limits.
