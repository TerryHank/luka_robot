# Luka patches carried on D-Robotics components

## PATCH-001 — tros_person_following configurable NavigateToPose action

Upstream baseline: `D-Robotics/tros_person_following@202e8c8a04dc41e3d3771daa131b852cc24f7c0d`.

Luka carries `navigate_to_pose_action_name` so that:
- dry-run uses `/luka_follow_dryrun/navigate_to_pose`;
- real mode uses `/navigate_to_pose`.

The locked upstream creates the action client with the literal relative name `navigate_to_pose`. The Luka patch is a safety boundary: dry-run tests must not accidentally address the real Nav2 action server.

Rules:
1. Never drop this patch during an upstream sync without equivalent upstream configurability.
2. Do not change the following algorithm inside this patch.
3. If upstream gains equivalent support, migrate config and pass dry-run acceptance before removing PATCH-001.
