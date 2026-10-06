# P5 MOT modes

Two intentionally different follow-acquisition modes are supported.

## selected (product default)

```text
YOLO26/Seg
 -> Luka tracker + explicit target policy
 -> Target Gate
 -> tros_person_following
```

No second MOT node is launched. This preserves selected-person semantics and
future identity/ReID policy.

## automatic (demo/controlled single-person mode)

```text
/luka/perception/person_targets
 -> D-Robotics hobot_mot/tros_mot_node
 -> /luka/perception/mot_targets
 -> Target Gate (auto selection)
 -> tros_person_following
```

The automatic gate only auto-selects when exactly one valid person is present.
It ignores Luka selected-mode track IDs because official MOT assigns its own
trajectory IDs.

## Identity boundary

The pinned official MOT is IOU/Kalman based and does not provide a supported
persistent ReID mode. Therefore:
- official `track_id` is a trajectory ID, not identity;
- automatic mode is not an identity-follow mode;
- selected mode remains the product path for "follow this person";
- an ID change still disarms following rather than silently switching people.
