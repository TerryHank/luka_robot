# P3 ROS-native person observations

## Motion-free outputs

- `/luka/perception/person_targets` — `ai_msgs/msg/PerceptionTargets`
- `/luka/perception/selected_track_id` — `std_msgs/msg/Int64`; `-1` means none
- `/luka/perception/person_diagnostics` — privacy-minimized JSON status

Targets include track ID, body ROI/confidence, depth validity, strong/weak
observation status, ambiguity, visibility, registered optical XYZ when valid,
projected body width/height, depth-valid fraction and RGB/depth skew.

They deliberately exclude names, face embeddings, voiceprints and product
account metadata.

## Compatibility boundary

`/api/people/follow-state` remains during migration so existing Dashboard code
does not break. The ROS observation topics are now the canonical robot
perception interface. P4 switches the follow Target Gate away from HTTP
polling; after that, the GET endpoint is strictly a compatibility/view mirror.

## Fail closed

A camera/perception invalidation publishes an empty `PerceptionTargets`.
The publisher has no motion publisher, service client or action client.
Failure to initialize/publish ROS observations cannot activate motion and does
not remove the legacy HTTP observation path.
