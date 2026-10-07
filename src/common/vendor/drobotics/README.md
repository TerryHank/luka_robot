# D-Robotics vendor integration

The repository root `vendor` path is a compatibility link to `common/vendor`; this directory is the canonical storage location.

Import a pinned source set with:

```bash
mkdir -p /tmp/luka-rdk-suite/src
vcs import /tmp/luka-rdk-suite/src < vendor/drobotics/rdks100-suite.repos
```

D-Robotics owns generic runtime/model/MOT/following/speech/LLM components.
Luka keeps DDSM hardware, target identity policy, segmentation-depth geometry, navigation safety, hotel semantics, memory, workflow and product UI behavior.

Read `PATCHES.md` before replacing a local official package.
