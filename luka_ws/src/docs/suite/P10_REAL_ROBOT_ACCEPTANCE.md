# P10 real-robot grey rollout

P10 is the first phase in which real motion is permitted. It must be performed
on the physical robot with an onsite operator and spotter. Repository changes
alone cannot satisfy P10.

## Non-negotiable safety chain

Both follow motion forms must stay inside Luka safety:

```text
tros_person_following
  |-- NavigateToPose
  |      -> Nav2
  |      -> velocity smoother
  |      -> /nx/nav_smoothed
  |      -> Luka heading guard
  |      -> /nx/nav_guarded
  |      -> collision monitor
  |      -> /nx/nav_safe
  |      -> ddsm_car_control
  |
  +-- direct turn/stop Twist
         -> /nx/nav_smoothed
         -> same Luka guard/collision chain
         -> /nx/nav_safe
         -> ddsm_car_control
```

Any graph showing the official follow node or an external component publishing
directly to the DDSM/base motor input is a test failure.

## Before motion

1. Checkout this feature branch and record the exact SHA.
2. Build the selected packages on the S100.
3. Run `bash system/scripts/p10_preflight_readonly.sh`.
4. Save its evidence directory.
5. Confirm the physical emergency-stop/kill method by hand.
6. Confirm an onsite spotter is present.
7. Confirm follow and navigation permissions are initially disabled.
8. For Stage 1 physically lift/suspend the drive wheels.
9. For Stage 2+ apply temporary limits no greater than 0.20 m/s linear and
   0.40 rad/s angular and independently read them back before motion.
10. Fill `P10_ACCEPTANCE_RECORD.md` while testing.

Do not continue to the next stage after any unexplained movement, wrong wheel
direction, stale TF, lost lidar, collision-monitor fault, wrong-person
selection, or failed cancellation.

## Stage order

The order is mandatory:

```text
1. wheels suspended
2. ground low speed
3. multi-person crossing
4. Nav2 environment cases
5. long-duration stability
```

A failure at one stage blocks later stages.

## Motion arming discipline

P10 real launch must never be a default boot behavior. The operator explicitly
starts the real-follow launch and explicitly enables navigation/following only
after the preflight and stage setup are complete.

When a target becomes stale, missing, weak, ambiguous, loses valid
segmentation-depth, changes track ID, or loses TF, the expected result is
**disable/cancel**, not target substitution.

## Evidence

Use `bash system/scripts/p10_capture_metrics.sh` before, during and after
long-duration testing. Add ROS bags or additional logs if available, but do not
replace the acceptance record with verbal claims.

The five P10 checklist items in the master plan remain unchecked until this
physical evidence exists.
