# Contract demonstration entrypoint rules

- Real ROS hardware/function demonstrations must be entered through a ROS2
  launch file; demo.sh must run ros2 launch. Offline Python checks alone do not
  constitute a functional demonstration.
- Related clauses may share a functional launch directory. Keep every original
  contract clause and logical number in manifest.json and audit.csv.
- Show live observable results: measured odometry, raw IMU axes, real scans or
  images. Label simulated/offline data explicitly; never call command integration
  measured encoder odometry.
- Keyboard commands must use the existing protected manual input. Preserve
  serial ownership, encoder/scan freshness, obstacle and timeout gates.
- Do not start a second driver/sensor owner. Reuse known running services.
- Ctrl+C and stop.sh must shut down only processes created by this launch.
- Environment/document/delivery inspections may use check.sh and must not be
  presented as a complete hardware demonstration or contract acceptance.
