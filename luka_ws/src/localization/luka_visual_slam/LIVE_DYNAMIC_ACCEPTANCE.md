# Real person-mask acceptance — 2026-10-08

PASS for the observed stationary-camera real-person segmentation/depth-filter chain. The user confirmed crossing the camera.
YOLO26 BPU inference used actual camera RGB; no synthetic mask was injected in this run.
The original timestamp and optical frame are preserved. Every observed paired filtered-depth frame was checked against real input depth and the matching real mask; outside-mask depth stayed unchanged.
Counts are accumulated pixel samples across frames, not distinct physical scene points.
RTAB-Map ran concurrently on filtered RGB-D input. No velocity or navigation goal was sent.

```json
{
  "mask_frames": 993,
  "nonzero_mask_frames": 82,
  "filtered_frames": 965,
  "verified_frames": 965,
  "verified_person_frames": 80,
  "removed_valid_depth_pixels": 2494845,
  "pixel_mismatch_frames": 0,
  "unpaired_frames": 0,
  "max_mask_age_s": 0.4433157444000244,
  "started": 1791467553.0043602,
  "inference_status": {
    "state": "publishing",
    "frames": 2853,
    "masked_frames": 102,
    "stale_dropped": 1,
    "age_s": 0.3229,
    "people": 0,
    "masked_pixels": 0,
    "inference_s": 0.0266,
    "source_stamp": 1791467672.493891
  },
  "snapshot": "/home/sunrise/luka_data/recordings/visual_slam/1791467553004422587",
  "snapshot_removed_pixels": 3567,
  "pass_real_mask_filter": true,
  "moving_loop_closure": "deferred: user can only keep camera stationary",
  "relocalization": "not tested in this stationary segmentation session",
  "human_confirmation": "User confirmed a person crossed the camera view; camera remained stationary",
  "snapshot_review": "Overlay inspected: person visible at right edge; mask is consistent with person region",
  "motion_commands_sent": false
}
```

Test scope: 120 seconds, one stationary camera and a person crossing. Segmentation accuracy against hand-labeled ground truth, other dynamic classes and long-duration stability were not evaluated.
Moving loop closure and geometric relocalization are deferred because the user currently cannot move the camera/robot.
