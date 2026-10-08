# P10 Physical Robot Acceptance Record

> This file is intentionally unchecked. It becomes evidence only when filled in
> on the physical RDK S100 robot by an onsite operator. Repository preparation
> is not a substitute for a real test.

## Build / identity

- Date:
- Operator:
- Spotter:
- Test location:
- Robot serial/asset:
- Branch: `feat/rdks100-suite-adaptation`
- Commit:
- RDK/TROS version:
- D-Robotics pinned source versions:
- YOLO runtime backend:
- Voice backend:
- LLM backend:
- Map:
- Battery:

## Mandatory preflight

- [ ] `bash system/scripts/p10_preflight_readonly.sh` returns success.
- [ ] Physical emergency-stop/kill method tested by the operator.
- [ ] `map -> base_footprint` and camera TF are fresh/correct.
- [ ] AMCL/localization is healthy.
- [ ] Costmap is healthy.
- [ ] Required lidar topics are fresh.
- [ ] Collision monitor is active.
- [ ] Base nav input is `/nx/nav_safe`.
- [ ] Follow is disabled before the test begins.
- [ ] Navigation permission is disabled before the test begins.

## Stage 1 — wheels suspended

- [ ] Enable/disable following behaves correctly.
- [ ] Forward/turn wheel directions are correct.
- [ ] Explicit cancel stops output.
- [ ] Physical emergency stop stops output.
- [ ] Target loss disarms/cancels.
- [ ] ID change disarms; no implicit person switch.
- Evidence directory:
- Notes:

## Stage 2 — ground low speed

Required temporary limits:
- linear: <= 0.20 m/s
- angular: <= 0.40 rad/s

- [ ] Limits independently verified before motion.
- [ ] Single person straight line.
- [ ] Person moves left/right.
- [ ] Stop/hold distance.
- [ ] Person approaches.
- [ ] Person moves away.
- [ ] Short occlusion.
- [ ] Lost target does not continue driving.
- Evidence directory:
- Notes:

## Stage 3 — multiple people

- [ ] User selects A.
- [ ] B crosses in front.
- [ ] A/B crossing.
- [ ] A leaves frame.
- [ ] A returns.
- [ ] Track-ID change observed safely.
- [ ] Robot never silently follows B as A.
- Evidence directory:
- Notes:

## Stage 4 — Nav2 scenarios

- [ ] Corridor.
- [ ] Corner.
- [ ] Doorway.
- [ ] Static obstacle.
- [ ] Costmap update.
- [ ] Person behind obstacle.
- [ ] Generated follow goal remains in a navigable/free location.
- [ ] Nav2 cancel after target invalidation is timely.
- Evidence directory:
- Notes:

## Stage 5 — long-duration stability

Duration:
- Start:
- End:

Record:
- [ ] CPU.
- [ ] BPU.
- [ ] Memory.
- [ ] Thermal.
- [ ] Camera/person FPS.
- [ ] End-to-end latency.
- [ ] Target loss count.
- [ ] MOT ID switch count.
- [ ] Nav2 cancel count.
- [ ] Safety stop count.
- [ ] No process leak / runaway memory.
- [ ] No unsafe motion observed.
- Evidence directory:
- Notes:

## Final P10 decision

- [ ] PASS — all five stages complete with evidence.
- [ ] FAIL — rollback required.
- [ ] CONDITIONAL — list unresolved defects below.

Unresolved defects:

Rollback commit/config used if required:
