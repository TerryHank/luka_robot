# Luka workspace

ROS 2 source is grouped by function. Root-level compatibility symlinks are removed.

- Configuration and local state: `common/config/`, `common/state/`
- Maps: `map/maps/`
- Startup and reset scripts: `system/bringup/`
- Service units: `system/services/`
- Command entrypoint: `system/luka.sh`
- Dashboard and console source: `visualization/console/`
- Installed tools compatibility directory: `system/runtime/tools/`
- Historical documentation: `docs/legacy/`

On the robot, source `/home/sunrise/luka_ws/system/environment.bash`.
Use `/home/sunrise/luka_ws/system/luka.sh status ws` to inspect services.
Service activation and motion retain their existing explicit controls.

`build/`, `install/`, `log/`, and `Log/` are local generated artifacts.
Models, credentials, and runtime state remain in their existing categorized directories;
removing a root shortcut does not delete its target.

Historical snapshots may record old paths. Current executable paths use the categorized directories.
