# NX manual control 2026-09-10

- Flydigi receiver enumerated as 045e:028e (Xbox360 compatibility); missing xpad built from upstream Linux v5.15 against installed 5.15.148-tegra headers. Installed updates/xpad.ko and depmod. joydev loaded; nvidia added to input group.
- Real input confirmed LB button 4, axes 0/1/3/4 range -1..1.
- nx-gamepad and nx-manual-base active, not enabled at boot. Dedicated command topic /nx/gamepad_unverified_cmd_vel retained despite verified mapping; no navigation inputs accepted.
- Low-speed limits: planar .05 m/s, yaw .15 rad/s, turbo same. Startup requires released LB and centered axes; then hold LB to drive. Adapter rejects stale joy/commands and missing encoder feedback. systemd watchdog 2s, independent ExecStopPost attempts stop on every motor, no auto restart.
- Read-only odom process stopped cleanly and its pose transferred. nx_localization.launch.py backed up as nx_localization.before_manual.py; config/nx_manual_mode suppresses read-only serial owner on future localization launches. Manual base owns RS485 and publishes measured /wheel/odom and TF. State checkpoint config/nx_manual_odom.json. Do not run old pulse commissioning tools alongside manual base.
- All four encoder positions valid, no send/feedback errors. Actual user-driven displacement observed in encoders: odom changed from x .02090,y .00011 to x .15591,y .03033 during validation, then zero estimated velocity. Speed feedback is disabled; speed_rpm placeholder zero must not be reported as a real measured RPM.
- Pure adapter checks passed: hold/release gating, stale command/joy/feedback rejection, nav isolation. No autonomous navigation or collision-avoidance guarantee for manual mode. Physical turn/lateral direction still subject to user observation.
- To stop manual control: sudo systemctl stop nx-manual-base. Do not remove nx_manual_mode while manual base runs. Restoring read-only mode requires stopped base, removing mode flag and restarting localization/reseeding map pose.

User observed reversed manual rotation; gamepad scale_yaw and turbo_scale_yaw changed to -0.15. Base kinematics/odometry unchanged. Restarted gamepad and verified live ROS parameters.
