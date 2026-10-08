# Visual SLAM integration acceptance — 2026-10-08

Built with colcon; seven pure contract tests passed. RGB-D mapping ran with the real Astra and isolated Nav2 planner.
ComputePathToPose returned SUCCEEDED and 4 poses; no controller or velocity publisher was created.
Mask transport tests used synthetic images in ROS_DOMAIN_ID=189; real segmentation input remains unavailable in this profile.
Localization loaded the copied real database with Mem/IncrementalMemory=false and emitted 25 info updates; no loop/proximity match ID was observed. This proves map load and mode integration, not successful geometric relocalization.
Duplicate namespace launch was rejected before creating a second pipeline. Initial custom-context probe failure was fixed using an explicit executor and rechecked.

```json
{
  "mapping": {
    "started": 1791466220.0232184,
    "odom_count": 655,
    "finite_odom_count": 655,
    "map_nodes": 2,
    "cloud_points": 3280,
    "map_cells": 8300,
    "experimental_tf_messages": 0,
    "private_tf_messages": 1211,
    "max_odom_age_s": 0.37476491928100586,
    "odom_frame": "rtabmap_rgbd_odom",
    "odom_child": "camera_link",
    "cloud_frame": "rtabmap_rgbd_map",
    "production_publishers": {
      "/map": [],
      "/odom": [],
      "/cmd_vel": []
    },
    "pass_stationary_initialization": true,
    "moving_mapping_and_loop_closure": "not tested"
  },
  "mask_transport": {
    "pass": true,
    "valid_outputs": 24,
    "stale_outputs": 0,
    "wrong_frame_outputs": 0,
    "missing_mask_outputs": 0,
    "ros_domain": 189
  },
  "planner": {
    "action": "/rtabmap_rgbd/compute_path_to_pose",
    "status": 4,
    "path_poses": 4,
    "map_frame": "rtabmap_rgbd_map",
    "cmd_vel_publishers": [],
    "motion_sent": false
  },
  "localization": {
    "messages": 25,
    "matched_ids": [],
    "last_ref_id": 202
  },
  "map_preservation": {
    "source_database": "/home/sunrise/luka_data/maps/visual_slam/1791466220337181426/map.db",
    "sha256_before": "9a443ce4a48e0c84ed1b1078927515d51b4e3f25634c7fc235fc15b29441c34d",
    "sha256_after": "9a443ce4a48e0c84ed1b1078927515d51b4e3f25634c7fc235fc15b29441c34d",
    "source_unchanged": true,
    "quick_check": "ok"
  }
}
```

Not tested: moving RGB-D SLAM accuracy, loop closure, physical navigation, real dynamic-person filtering, external VIO.
Production localization/Nav2 configuration was not edited or switched. Core RTAB-Map source remains unbuilt; Humble 0.23.7 binaries are used.

The localization test used a bounded transient service; its runtime limit expired after observation. The service was stopped/reset afterwards. No successful loop/proximity match was claimed.

## Subsequent real dynamic-mask acceptance

Real BPU person masks and depth filtering passed a 120-second fixed-camera trial. See LIVE_DYNAMIC_ACCEPTANCE.md; it supersedes earlier statements that a real mask stream was unavailable. Moving loop closure and geometric relocalization remain deferred.
