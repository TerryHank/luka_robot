# Current System Inventory

Date: 2026-10-04 (Asia/Shanghai)
Workspace: /home/sunrise/luka_ws
Legacy workspace: /home/sunrise/luka_s100 (not modified by this change)

## ROS and runtime

- Ubuntu ARM64 target: RDK S100.
- ROS 2 distribution: Humble.
- ROS_DOMAIN_ID: 87.
- ROS_LOCALHOST_ONLY: 1.
- RMW: rmw_cyclonedds_cpp.
- Python worker environment: /home/sunrise/luka_ws/perception/person_follow/yolo26_venv.
- OSNet body appearance ReID: disabled by service override NX_APPEARANCE_REID_ENABLED=0.
- CPU face recognition: disabled by NX_FACE_ENABLED=0.

## Camera

- Driver: Orbbec/Astra RGB-D driver.
- RGB: /camera/color/image_raw (sensor_msgs/msg/Image), 640x480, about 30 Hz.
- Depth: /camera/depth/image_raw (sensor_msgs/msg/Image), 640x480, about 30 Hz.
- RGB CameraInfo: /camera/color/camera_info (sensor_msgs/msg/CameraInfo).
- Depth CameraInfo: /camera/depth/camera_info (sensor_msgs/msg/CameraInfo).
- Extrinsics: /camera/depth_to_color (orbbec_camera_msgs/msg/Extrinsics).
- Camera frame observed in CameraInfo: camera_color_optical_frame.
- The depth CameraInfo uses the same optical frame; the driver publishes registered RGB-D data.
- No custom approximate-time synchronizer node is added; the existing worker consumes the driver frames and validates frame age.

## Detection and segmentation

- Model source: /home/sunrise/yolo26m-objv1-seg.pt.
- BPU model: /home/sunrise/luka_ws/perception/person_follow/models/bpu_yolo26/yolo26m_objv1_seg_bpu_nashe_640x640_nv12.hbm.
- Detector: yolo26_seg, BPU runtime.
- Person filter: class_id 0; public detector output is person-only.
- Segmentation mask reconstruction and depth statistics remain CPU post-processing; the neural network inference remains on BPU.
- Current depth method: selected segmentation mask valid-pixel trimmed mean, diagnostic name selected_seg_depth_valid / seg_valid_trimmed_mean, trim_ratio=0.15. Invalid, zero and out-of-range pixels are removed before trimming.

## Tracking and target selection

- MOT-related package installed: hobot_mot.
- The running worker uses its bounded IoU/depth tracker and publishes selected targets through the bridge; the standalone hobot_mot node is not started in the current bring-up.
- GUI selection is authoritative: the user selects a person in the page, and the bridge publishes only that selected track.
- OSNet/ReID is disabled, so a lost target is not recovered by appearance embeddings. A new target must be selected again.
- No face recognition or identity database is required for the follow path.

## Following and navigation

- Official package installed: tros_person_following.
- Custom package: luka_person_following.
- Preview launch: selected_follow.launch.py dry_run:=true (currently running for no-motion validation).
- Real launch: selected_follow.launch.py dry_run:=false.
- Selected bridge topic: /luka/selected_seg_targets (ai_msgs/msg/PerceptionTargets).
- Adapter diagnostic: /luka_person_following/adapter_status (std_msgs/msg/String).
- Follow enable service: /luka_person_following/set_enabled (std_srvs/srv/SetBool).
- Navigation permission service: /nx/navigation_enable (std_srvs/srv/SetBool).
- Nav2 actions available: /navigate_to_pose and /luka_follow_dryrun/navigate_to_pose.
- Motion outputs are not enabled by the preview launch.

## TF and base

- The follow launch publishes base_link -> base_footprint and the configured Astra mount transform.
- User-provided mount: vehicle center, 0.70 m above ground, level and facing forward.
- Camera optical frame is connected after the follow launch is running; robot_tf_ready is reported as 1.

## Bottom line and plan deviations

The existing workspace already contains the Seg x registered depth x track x official following chain. The supplied plan describes a new minimal architecture, but replacing the existing chain would duplicate components and risk the accepted GUI-selected-target behavior. The following plan items are therefore intentionally retained as current design choices:

- GUI-selected target is retained instead of automatic nearest-person selection.
- Official tros_person_following/Nav2 is retained; a separate simple /cmd_vel P follower is not added.
- The existing Seg-depth estimator is retained and now uses trimmed mean inside the selected mask; no second depth estimator is introduced.
- OSNet/ReID is now fully disabled, as required by the plan.

