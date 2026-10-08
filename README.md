# luka_data backup

Public snapshot of `/home/sunrise/luka_data`, captured on 2026-10-08.
Model weights, private credentials, generated caches and live sockets are excluded.
Exact included files, hashes, symlink targets and exclusions are in BACKUP_MANIFEST.json.

## Restore on Linux

Install Git LFS first, then clone both repositories next to each other:

```bash
git clone --branch dev https://github.com/TerryHank/luka_ws.git ~/luka_ws
git clone --branch dev https://github.com/TerryHank/luka_data.git ~/luka_data
git -C ~/luka_ws lfs pull
git -C ~/luka_data lfs pull
```

Linux symlinks and executable flags are preserved. Absolute links targeting `/home/sunrise/`
need adaptation when restoring under another username. Some links refer to external dependencies
outside these two directories; those targets are not included in this snapshot.
Restore models and private configuration separately, install system/ROS/vendor dependencies,
and rebuild with `colcon build --base-paths src`. This backup does not include build/install/log
or systemd files outside the requested directories and is not a verified full-system image.
