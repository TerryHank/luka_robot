# Navigation parity and bathroom test — 2026-09-10

User reported stopping halfway to bathroom and slow driving versus RK3588. Current original RK3588 192.168.3.150 was unreachable; used previously migrated original source/configs.

## Changes applied
- Restored original MPPI Omni settings (15 Hz, 900 samples, 30 steps), original velocity/acceleration limits and critics. Forward max .4 m/s, lateral controller max .42, angular controller max 1.6. Base clamp .42 m/s / 1.6 rad/s, original lateral scale .8 and angular scale .7. Manual joystick remains low speed.
- Restored original lateral_escape_guard forward_facing control, active timed escape false as in original launch. Pipeline: Nav2 -> smoother -> original heading guard -> collision monitor -> NX base gate. Velocity smoother runs 15 Hz to match controller rather than 50 Hz.
- Ported original recovery-tree sequence to installed Humble: removed unsupported WouldA* conditions/error_code ports while preserving retries, costmap clearing and backup-before-spin recovery. This is an explicit compatibility adaptation, not a claim of byte-identical original execution.
- Lower fused scan publishing cap 20 Hz (actual limited by ~10 Hz sensors), avoiding previous 5 Hz cap that yielded 3–4 Hz. Collision source timestamp allowance .8 s to accommodate scan acquisition/fusion delay. Base still zeroes navigation immediately when its fresh input checks fail; waits up to 2 s for transient recovery, then cancels persistent faults. LB always cancels without auto-resume. Added pause/cancel reason logs.
- Real scans repeatedly showed shifting bracket-edge returns INSIDE vehicle envelope; observed clusters x .335–.376, y .148–.218, earlier .365/.19. Consolidated low-lidar front-left bracket mask x [.280,.390], y [.100,.230], entirely within known protected hull; outer obstacle points remain. Vehicle footprint x[-.28,.39], y[-.23,.23], padding .02. Pure boundary tests confirm outside points retained.
- Identified localization jumps on sensor restarts from overly broad .2m initialization. Read-only local scan matching recovered a position near pre-restart pose, ~86% endpoints within .15 m of map obstacles. Reduced same-location restart seed covariance to .0025 (5 cm / ~3 deg std), preserving continuity; this is not an absolute pose-accuracy claim.
- Web banner now shows .4 m/s upper limit and reports connection loss rather than retaining stale navigation status silently.

## Real motion verification
1. Bathroom test succeeded at 15:44:22 after final corrections.
2. Complete bathroom -> kitchen -> bathroom roundtrip succeeded; exact application-level observations saved in bathroom_roundtrip_result.json. Kitchen leg ~6.59 s; return bathroom leg ~18.72 s including turning/final heading. Both NavigateToPose results were succeeded. Explicit stop issued afterward; robot left at bathroom.
3. Base logs showed nonzero cmd_vel_nav/RPM targets during motion, zero commands afterward. Final map estimate near bathroom x -1.1545,y -.1374,yaw .00801 (saved POI -1.1098,-.1434,0). This is estimated localization, not externally measured accuracy.
4. Unit checks passed for manual timeout/release, temporary zeroing and persistent nav fault cancellation, LB cancellation/no-auto-resume, and bracket boundaries. No further real movement tests after roundtrip success.

## Scope still distinct
Navigation core now reuses original planning/controller/heading/recovery behavior with NX hardware and safety adaptation. Still NOT a claim that every RK3588 function is fully migrated/accepted: original named mission/semantic dispatch, final approach service, patrol scheduler, EKF/IMU fusion chain, speech/follow/cross-floor workflows are not all running in this NX acceptance setup. Dashboard currently sends verified floor-4 waypoints directly to Nav2. Original RKNN backends also remain separate porting work. Don't claim full-vehicle parity from this successful route.
