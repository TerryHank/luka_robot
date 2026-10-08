# Luka workspace architecture (mandatory)

All work in this repository must preserve this layout:

    ~/luka_ws/
        src/
            sensing/
            localization/
            perception/
            planning/
            control/
            map/
            common/
            system/
            visualization/
            ...other source categories...
        build/
        install/
        log/

    ~/luka_data/
        maps/
        ml_models/
        recordings/
            bags/

## Rules for every future change

- All ROS packages and source categories belong under luka_ws/src/. Never create
  sensing/, localization/, perception/, control/, planning/, system/, common/,
  map/, or any new source domain directly under the workspace root.
- Supporting source, examples, documentation and evaluation code also belong
  under src/. Keep root README.md, AGENTS.md and Git/editor metadata at the root.
- Navigation maps, model weights, recordings and bags belong under luka_data/.
  Do not copy them back into src/ or create root compatibility symlinks.
- Configuration and launch code belong under src/common/config/ and
  src/system/ as appropriate; they must reference the canonical source/data paths.
- Build from luka_ws with colcon build --base-paths src. Generated artifacts
  stay in build/, install/ and log/. Exclude virtual environments and vendored
  non-package tools from colcon discovery with COLCON_IGNORE.
- Keep each ROS package name unique. Inspect colcon list --base-paths src
  before and after changes that add, move or restore packages.
- Old backups, historical branches and upstream files are reference material.
  Adapt them to this layout before integrating them. Never restore an old root
  layout through a pull, merge, checkout, extraction or recovery operation.
- Run python3 src/system/scripts/check_workspace_root.py before committing
  structural changes or publishing source snapshots.
- Preserve existing uncommitted work. Do not reset or overwrite the checkout
  to enforce this architecture.

## Package and functional uniqueness

- Before and after package/entrypoint changes, run
  `python3 src/system/scripts/check_workspace_uniqueness.py` in addition to the root-layout checker.
- Read `src/common/config/functional_owners.json` before adding another implementation
  or launcher for a function. Update the owner registry when a canonical path changes.
- Existing compatibility names must delegate to the canonical implementation;
  do not restore duplicate controllers, copied configuration or old bridge pipelines.
- Historical code snapshots belong outside luka_ws, under a checked recoverable archive.
  Do not restore .before/.pre/.bak/.orig source copies into the current source tree.
- Interface packages, application layers, default templates and supported hardware profiles
  are complementary when their roles differ. Do not delete them based on similar names or timestamps.
- Orbbec ROS acquisition owns log/owners/astra-camera.lock. ROS-image consumers
  use their own process lock and must not open the USB camera or lock out the physical owner.
  Preserve existing serial/velocity ownership safeguards.
