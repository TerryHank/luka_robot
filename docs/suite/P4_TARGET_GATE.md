# P4 Luka Target Gate

The follow adapter is now a ROS-native **Target Gate**, not an HTTP-to-ROS bridge.

Canonical flow:

```text
/luka/perception/person_targets
/luka/perception/selected_track_id
              |
              v
       Luka Target Gate
              |
              +-- stale/weak/ambiguous/depth/TF/ID fail-close
              |
              v
/luka/follow/selected_target
              |
              v
D-Robotics tros_person_following
```

A compatibility publisher remains at `/luka/selected_seg_targets` while older
diagnostics/tests are migrated.

## Safety rules

- default mode requires an explicit selected track;
- auto-first-person remains available as an opt-in compatibility/demo mode;
- a changed trajectory ID disarms following rather than treating the new ID as
  the same person;
- only a target carrying the P3 `seg_depth_trimmed_mean` proof and valid
  registered-depth geometry can pass;
- stale input (>0.5 s), missing target, weak/ambiguous association, invalid
  depth, depth jump or unavailable TF disarms following;
- a short depth-invalid hold remains bounded by `depth_invalid_grace_sec`;
- controller cancellation is synchronized before changed/empty observations are
  released to the official state machine.

The deprecated `status_url` launch parameter remains accepted only so old
launch commands do not fail. The node contains no HTTP client.
