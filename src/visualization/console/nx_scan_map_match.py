"""Small fail-closed scan-to-static-map consistency check for AMCL poses."""

import math
import time

import cv2
import numpy as np
from rclpy.duration import Duration
from rclpy.time import Time


class ScanMapMatcher:
    """Score whether current laser endpoints land on mapped obstacles."""

    def __init__(self, node, scan_topic="/scan"):
        from nav_msgs.msg import OccupancyGrid
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import LaserScan
        from rclpy.qos import qos_profile_sensor_data

        self.node = node
        self.map_msg = None
        self.map_field = None
        self.map_received = 0.0
        self.scan_msg = None
        self.scan_received = 0.0
        self.map_generation = 0
        self.cache_key = None
        self.cache = self.empty("waiting_for_map_and_scan")
        map_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.map_sub = node.create_subscription(
            OccupancyGrid, "/map", self.on_map, map_qos
        )
        self.scan_sub = node.create_subscription(
            LaserScan, scan_topic, self.on_scan, qos_profile_sensor_data
        )

    @staticmethod
    def empty(reason):
        return {
            "valid": False,
            "reason": reason,
            "known_endpoints": 0,
            "median_m": None,
            "within_15cm": None,
            "checked_at": 0.0,
        }

    def on_map(self, msg):
        try:
            info = msg.info
            grid = np.asarray(msg.data, dtype=np.int16).reshape(
                info.height, info.width
            )
            # Occupied cells are zeroes for the distance transform. Unknown
            # cells are excluded from scoring below.
            field = cv2.distanceTransform(
                (grid < 50).astype(np.uint8), cv2.DIST_L2, 5
            ) * float(info.resolution)
            self.map_msg = msg
            self.map_field = field
            self.map_received = time.monotonic()
            self.map_generation += 1
            self.cache_key = None
        except (TypeError, ValueError, OverflowError, cv2.error):
            self.map_msg = self.map_field = None
            self.cache = self.empty("invalid_map")

    def on_scan(self, msg):
        self.scan_msg = msg
        self.scan_received = time.monotonic()
        self.cache_key = None

    @staticmethod
    def yaw(q):
        return math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )

    def refine_near(self, seed):
        """Refine a remembered pose from one scan without moving the robot.

        Search stays within 30 cm / 20 degrees of the saved pose; a far-away
        match cannot silently replace it. The caller still validates the
        selected pose against live scans before allowing navigation.
        """
        seed=tuple(float(value) for value in seed)
        if self.map_msg is None:
            return seed,self.empty('waiting_for_map')
        info=self.map_msg.info
        origin=info.origin
        map_yaw=self.yaw(origin.orientation)
        grid=np.asarray(self.map_msg.data,dtype=np.int16).reshape(info.height,info.width)

        def footprint_free(candidate):
            cx,cy,heading=candidate
            ch,sh=math.cos(heading),math.sin(heading)
            cm,sm=math.cos(map_yaw),math.sin(map_yaw)
            for bx,by in ((0.,0.),(.25,.16),(.25,-.16),(-.25,.16),(-.25,-.16)):
                wx=cx+ch*bx-sh*by-origin.position.x
                wy=cy+sh*bx+ch*by-origin.position.y
                gx=int(math.floor((cm*wx+sm*wy)/info.resolution))
                gy=int(math.floor((-sm*wx+cm*wy)/info.resolution))
                if gx<0 or gy<0 or gx>=info.width or gy>=info.height or grid[gy,gx]!=0:
                    return False
            return True

        current=seed
        initial=self.score(current,check_heading=False)
        best=initial
        if initial.get('known_endpoints',0)<80:
            return current,initial
        for xy_step,yaw_step in ((.12,.12),(.05,.05),(.02,.02)):
            winner=current
            for dx in (-xy_step,0.,xy_step):
                for dy in (-xy_step,0.,xy_step):
                    for da in (-yaw_step,0.,yaw_step):
                        candidate=(current[0]+dx,current[1]+dy,
                                   math.atan2(math.sin(current[2]+da),math.cos(current[2]+da)))
                        if math.hypot(candidate[0]-seed[0],candidate[1]-seed[1])>.30:
                            continue
                        if abs(math.atan2(math.sin(candidate[2]-seed[2]),
                                          math.cos(candidate[2]-seed[2])))>.35:
                            continue
                        if not footprint_free(candidate):
                            continue
                        result=self.score(candidate,check_heading=False)
                        if result.get('known_endpoints',0)<80:
                            continue
                        quality=(result.get('within_15cm') or 0.)-.7*(result.get('median_m') or 1.)
                        best_quality=(best.get('within_15cm') or 0.)-.7*(best.get('median_m') or 1.)
                        if quality>best_quality:
                            best=result;winner=candidate
            current=winner
        return current,self.score(current,check_heading=True)

    def score(self, pose, check_heading=True):
        """Return alignment for map pose=(x,y,yaw), failing closed on stale data."""
        now = time.monotonic()
        if self.map_msg is None or self.map_field is None:
            return self.empty("waiting_for_map")
        if self.scan_msg is None:
            return self.empty("waiting_for_scan")
        # OccupancyGrid is transient-local and static maps are normally only
        # published once. Its age is not a staleness signal; ObjectPoseContext
        # separately verifies that the retained grid equals the active map file.
        if now - self.scan_received > 1.0:
            return self.empty("scan_stale")

        key = (self.map_generation, self.scan_received, bool(check_heading),
               *[round(float(v), 3) for v in pose])
        if key == self.cache_key:
            return dict(self.cache)

        try:
            scan = self.scan_msg
            frame = scan.header.frame_id.lstrip("/")
            if not frame:
                return self.empty("scan_frame_missing")
            tf = self.node.object_pose_context.buffer.lookup_transform(
                "base_link", frame, Time.from_msg(scan.header.stamp),
                timeout=Duration(seconds=0.05),
            )
            tr, qr = tf.transform.translation, tf.transform.rotation
            laser_yaw = self.yaw(qr)
            cl, sl = math.cos(laser_yaw), math.sin(laser_yaw)
            cb, sb = math.cos(float(pose[2])), math.sin(float(pose[2]))

            ranges = np.asarray(scan.ranges, dtype=np.float32)
            stride = max(1, len(ranges) // 240)
            indices = np.arange(0, len(ranges), stride, dtype=np.int32)
            rr = ranges[indices]
            aa = float(scan.angle_min) + indices * float(scan.angle_increment)
            valid = (np.isfinite(rr)
                     & (rr >= max(0.20, float(scan.range_min)))
                     & (rr <= min(8.0, float(scan.range_max))))
            rr, aa = rr[valid], aa[valid]
            if len(rr) < 40:
                return self.empty("too_few_valid_rays")

            # Laser frame -> base_link -> map.
            lx, ly = rr * np.cos(aa), rr * np.sin(aa)
            bx = tr.x + cl * lx - sl * ly
            by = tr.y + sl * lx + cl * ly
            x0 = float(pose[0]) + cb * tr.x - sb * tr.y
            y0 = float(pose[1]) + sb * tr.x + cb * tr.y
            wx = x0 + cb * (bx - tr.x) - sb * (by - tr.y)
            wy = y0 + sb * (bx - tr.x) + cb * (by - tr.y)

            info, origin = self.map_msg.info, self.map_msg.info.origin
            map_yaw = self.yaw(origin.orientation)
            dx, dy = wx - origin.position.x, wy - origin.position.y
            cm, sm = math.cos(map_yaw), math.sin(map_yaw)
            mx, my = cm * dx + sm * dy, -sm * dx + cm * dy
            gx = np.floor(mx / float(info.resolution)).astype(np.int32)
            gy = np.floor(my / float(info.resolution)).astype(np.int32)
            inside = ((gx >= 0) & (gx < int(info.width))
                      & (gy >= 0) & (gy < int(info.height)))
            gx, gy = gx[inside], gy[inside]
            if len(gx) == 0:
                return self.empty("scan_outside_map")
            grid = np.asarray(self.map_msg.data, dtype=np.int16).reshape(
                info.height, info.width
            )
            known = grid[gy, gx] >= 0
            gx, gy = gx[known], gy[known]
            if len(gx) < 40:
                return self.empty("too_few_known_map_rays")

            distances = self.map_field[gy, gx]
            median = float(np.median(distances))
            fraction = float(np.mean(distances <= 0.15))
            # Values are calibrated against a live floor-4 scan: median 5 cm,
            # 70% of endpoints within 15 cm. Dynamic objects remain tolerated.
            good = median <= 0.20 and fraction >= 0.55
            result = {
                "valid": good,
                "reason": "scan_matches_map" if good else "scan_map_mismatch",
                "known_endpoints": int(len(distances)),
                "median_m": median,
                "within_15cm": fraction,
                "checked_at": now,
            }
            if check_heading:
                # A square or repetitive room can produce a plausible scan
                # match at several quarter-turn headings. Compare the current
                # AMCL heading with those alternatives before calling it unique.
                candidates = [dict(yaw_deg=round(math.degrees(float(pose[2])) % 360.0, 1),
                                   valid=good, median_m=median,
                                   within_15cm=fraction)]
                for turn in (math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0):
                    alt_yaw = math.atan2(math.sin(float(pose[2]) + turn),
                                         math.cos(float(pose[2]) + turn))
                    alt = self.score((pose[0], pose[1], alt_yaw), check_heading=False)
                    candidates.append(dict(
                        yaw_deg=round(math.degrees(alt_yaw) % 360.0, 1),
                        valid=bool(alt.get("valid")),
                        median_m=alt.get("median_m"),
                        within_15cm=alt.get("within_15cm"),
                    ))
                passing = [c for c in candidates if c["valid"]]
                passing.sort(key=lambda c: (c["median_m"], -c["within_15cm"]))
                result["heading_hypotheses"] = candidates
                result["heading_candidate_count"] = len(passing)
                result["best_heading_deg"] = passing[0]["yaw_deg"] if passing else None
                current = candidates[0]
                # Several headings may pass the broad map-match threshold.
                # Count them for diagnostics, but accept the current heading
                # when it clearly dominates every alternative.
                dominant = len(passing) == 1 and current["valid"]
                if len(passing) > 1:
                    best, second = passing[0], passing[1]
                    tied = (abs(best["median_m"] - second["median_m"]) <= 0.04
                            and abs(best["within_15cm"] - second["within_15cm"]) <= 0.10)
                    current_is_best = (abs(current["median_m"] - best["median_m"]) <= 0.01
                                       and abs(current["within_15cm"] - best["within_15cm"]) <= 0.03)
                    if tied:
                        result["valid"] = False
                        result["reason"] = "heading_ambiguous"
                    elif not current_is_best:
                        result["valid"] = False
                        result["reason"] = "heading_hypothesis_conflict"
                    else:
                        dominant = True
                elif passing and not current["valid"]:
                    result["valid"] = False
                    result["reason"] = "heading_hypothesis_conflict"
                result["heading_unique"] = bool(dominant and result["valid"])
            self.cache_key, self.cache = key, result
            return dict(result)
        except Exception as exc:
            return self.empty("tf_or_match_error:" + str(exc)[:120])
