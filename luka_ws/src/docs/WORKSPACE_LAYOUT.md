# Luka runtime data

Runtime/generated data is intentionally outside the Git workspace:

```text
~/luka_data/
├── maps/
├── ml_models/
└── recordings/
    └── bags/
```

Initialize it with:

```bash
cd ~/luka_ws
bash scripts/bootstrap_workspace_layout.sh
```

The bootstrap script can restore the maps and stereo-calibration captures that
were historically tracked in Git from commit
`eb935d1ac7973dfabb7fe7c8771cc9fd04510b6d`.

Environment variables:
- `LUKA_WS` defaults to the repository root.
- `LUKA_DATA` defaults to `~/luka_data`.
- `LUKA_MAPS_DIR`, `LUKA_MODELS_DIR`, `LUKA_RECORDINGS_DIR`,
  `LUKA_BAGS_DIR` derive from `LUKA_DATA`.
