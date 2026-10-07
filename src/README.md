# Luka ROS 2 source tree

Canonical source code lives under this directory.

- `sensing/` — camera, lidar and sensor drivers
- `localization/` — localization integration
- `mapping/` — semantic-map and map tooling; runtime maps live in `~/luka_data/maps`
- `perception/` — detection, tracking and spatial perception
- `planning/` — exploration and planning packages
- `control/` — base, follow and low-level control
- `system/` — bringup, interaction, product and runtime services
- `visualization/` — dashboard and console tooling
- `common/` — shared config/vendor/runtime compatibility assets
- `testing/` — e2e/evaluator/examples and is excluded from colcon

New code should use `$LUKA_WS/src/...` or ROS package discovery. Legacy
root-level paths are compatibility links only.
