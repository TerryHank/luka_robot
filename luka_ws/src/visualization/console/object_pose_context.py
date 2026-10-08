"""Timestamped, quality-gated observation context; never commands robot motion."""
import hashlib
import json
import math
from pathlib import Path
import time

from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.duration import Duration
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_srvs.srv import Empty
from tf2_ros import Buffer, TransformListener


def _stamp(msg):
    return float(msg.header.stamp.sec) + msg.header.stamp.nanosec / 1e9


COVARIANCE_ROUNDOFF_TOLERANCE = 1e-10


def normalize_planar_covariance(covariance):
    """Validate AMCL x/y/yaw variances, tolerating only tiny finite roundoff.

    AMCL computes E[x^2]-E[x]^2 and circular variance using a logarithm;
    concentrated particles can produce negative values around machine precision.
    Positive values are preserved. NaN/Inf and meaningful negatives remain invalid.
    Raw nonfinite values are strings so JSON never emits invalid NaN/Infinity tokens.
    Near-zero particle spread does not establish physical localization accuracy.
    """
    result = dict(covariance_status='invalid_shape', covariance_raw=None,
                  covariance_diagonal=None, covariance_near_zero=False, sigma=None)
    try:
        values = [float(covariance[i]) for i in (0, 7, 35)]
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        return result
    result['covariance_raw'] = [v if math.isfinite(v) else str(v) for v in values]
    if not all(math.isfinite(v) for v in values):
        result['covariance_status'] = 'invalid_nonfinite'
    elif any(v < -COVARIANCE_ROUNDOFF_TOLERANCE for v in values):
        result['covariance_status'] = 'invalid_negative'
    else:
        diagonal = [max(0., v) for v in values]
        result.update(covariance_status='roundoff_clamped' if any(v < 0. for v in values) else 'valid',
                      covariance_diagonal=diagonal, sigma=[math.sqrt(v) for v in diagonal],
                      covariance_near_zero=all(v <= COVARIANCE_ROUNDOFF_TOLERANCE for v in diagonal))
    return result


def occupancy_fingerprint(width, height, resolution, origin, cells):
    """Hash actual coordinates/cells; exclude publication time/YAML formatting.

    Seven decimals normalize OccupancyGrid's float32 resolution against YAML.
    Origin is [x, y, z, qx, qy, qz, qw].
    """
    geometry = [int(width), int(height), round(float(resolution), 7)]
    geometry.extend(round(float(v), 7) for v in origin)
    if width <= 0 or height <= 0 or resolution <= 0 or len(cells) != width * height:
        raise ValueError('invalid map dimensions')
    if not all(math.isfinite(v) for v in geometry):
        raise ValueError('invalid map geometry')
    data = bytes((int(v) & 255 for v in cells))
    return hashlib.sha256(json.dumps(geometry, separators=(',', ':')).encode() + b'\0' + data).hexdigest()


def map_scope(node):
    """Shared patrol/query/bring contract: never infer live scope from UI alone."""
    context = getattr(node, 'object_pose_context', None)
    if context is None:
        return dict(floor_id=None, map_id=None, map_version=None,
                    map_scope_valid=False, map_scope_reason='map_context_unavailable')
    return context.map_scope()


def _inside_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if (a[1] > y) != (b[1] > y):
            cross = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < cross:
                inside = not inside
    return inside


class ObjectPoseContext:
    def __init__(self, node):
        self.node = node
        self.buffer = Buffer(cache_time=Duration(seconds=30))
        self.listener = TransformListener(self.buffer, node)
        self.odom = None
        self.odom_received = 0.
        self.still_since = None
        self.amcl = None
        self.amcl_received = 0.
        self.relocalized_at = 0.
        self.live_map = None
        self.map_changed_at = 0.
        self._file_cache = {}
        self._json_cache = {}
        self._refresh_at = 0.
        self._refresh_future = None
        self.refresh_client = node.create_client(Empty, '/request_nomotion_update')
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.sub = node.create_subscription(Odometry, '/wheel/odom', self.on_odom, 10)
        self.map_sub = node.create_subscription(OccupancyGrid, '/map', self.on_map, qos)
        self.pose_sub = node.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.on_amcl, qos)
        self.initial_sub = node.create_subscription(PoseWithCovarianceStamped, '/initialpose', self.on_initialpose, 10)

    def on_odom(self, msg):
        now = time.monotonic()
        v = msg.twist.twist
        still = abs(v.linear.x) < .02 and abs(v.linear.y) < .02 and abs(v.angular.z) < .03
        if not still:
            self.still_since = None
        elif self.still_since is None or now - self.odom_received > .5:
            self.still_since = now
        self.odom, self.odom_received = msg, now

    def on_amcl(self, msg):
        self.amcl, self.amcl_received = msg, time.monotonic()

    def on_initialpose(self, _msg):
        self.relocalized_at = time.time()

    def _maybe_refresh_localization(self, result, age, now):
        """Request a fresh laser update at rest; never publish a pose or movement."""
        scan_at = getattr(self.node, 'last', {}).get('scan', 0.)
        if (not result['stationary'] or not result['map_scope_valid'] or age <= 10.
                or not scan_at or now - scan_at > 2. or now - self._refresh_at < 10.):
            return False
        if self._refresh_future is not None and not self._refresh_future.done():
            # A disappeared/restarted service can leave its client future pending.
            self._refresh_future.cancel()
        if not self.refresh_client.service_is_ready():
            return False
        self._refresh_at = now
        try:
            self._refresh_future = self.refresh_client.call_async(Empty.Request())
            return True
        except Exception:
            self._refresh_future = None
            return False

    def on_map(self, msg):
        try:
            info = msg.info
            p, q = info.origin.position, info.origin.orientation
            digest = occupancy_fingerprint(info.width, info.height, info.resolution,
                                           [p.x, p.y, p.z, q.x, q.y, q.z, q.w], msg.data)
            if self.live_map and self.live_map['fingerprint'] != digest:
                self.map_changed_at = time.time()
            self.live_map = dict(fingerprint=digest, frame_id=msg.header.frame_id.lstrip('/'),
                                 received_at=time.monotonic())
        except (TypeError, ValueError, OverflowError):
            self.live_map = None

    def _read_json(self, path):
        path = Path(path)
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = self._json_cache.get(str(path))
        if cached and cached[0] == key:
            return cached[1]
        value = json.loads(path.read_text(encoding='utf-8'))
        self._json_cache[str(path)] = (key, value)
        return value

    def _expected_map(self, path):
        """Match live /map to active map file, not a file selected for viewing."""
        import cv2
        import numpy as np
        import yaml
        path = Path(path)
        if not path.is_absolute():
            path = Path(self.node.workspace) / path
        stat = path.stat()
        cached = self._file_cache.get(str(path))
        if cached:
            image_stat = Path(cached['image']).stat()
            key = (stat.st_mtime_ns, stat.st_size, image_stat.st_mtime_ns, image_stat.st_size)
            if key == cached['key']:
                return cached['fingerprint']
        doc = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if doc.get('mode', 'trinary') != 'trinary':
            raise ValueError('unsupported map encoding')
        image = Path(doc['image'])
        if not image.is_absolute():
            image = path.parent / image
        image_stat = image.stat()
        pixels = cv2.imread(str(image), cv2.IMREAD_UNCHANGED)
        if pixels is None or pixels.ndim != 2 or pixels.dtype != np.uint8:
            raise ValueError('map must be an 8-bit grayscale image')
        occupancy = pixels.astype(np.float64) / 255.
        if not bool(doc.get('negate', 0)):
            occupancy = 1. - occupancy
        cells = np.full(pixels.shape, -1, dtype=np.int8)
        cells[occupancy > float(doc.get('occupied_thresh', .65))] = 100
        cells[occupancy < float(doc.get('free_thresh', .25))] = 0
        x, y, yaw = doc.get('origin', [0., 0., 0.])
        digest = occupancy_fingerprint(pixels.shape[1], pixels.shape[0], float(doc['resolution']),
                                       [x, y, 0., 0., 0., math.sin(yaw / 2), math.cos(yaw / 2)],
                                       np.flipud(cells).ravel())
        self._file_cache[str(path)] = dict(fingerprint=digest, image=str(image),
            key=(stat.st_mtime_ns, stat.st_size, image_stat.st_mtime_ns, image_stat.st_size))
        return digest

    def map_scope(self):
        result = dict(floor_id=None, map_id=None, map_version=None,
                      map_scope_valid=False, map_scope_reason='no_live_map')
        try:
            active = self._read_json(Path(self.node.workspace) / 'common/config' / 'active_floor_context.json')
            floor = active.get('floor_id')
            if not isinstance(floor, str) or not floor.startswith('floor_'):
                raise ValueError('active floor unknown')
            result['floor_id'] = floor
            live = self.live_map
            if not live:
                return result
            digest = live['fingerprint']
            result.update(map_id=f'{floor}:{digest[:20]}', map_version=digest)
            if live['frame_id'] != 'map':
                result['map_scope_reason'] = 'unexpected_map_frame'
            elif getattr(self.node, 'current_floor_id', None) != floor:
                result['map_scope_reason'] = 'display_floor_differs_from_active_floor'
            elif self._expected_map(active['map_file']) != digest:
                result['map_scope_reason'] = 'live_map_differs_from_active_map_file'
            else:
                result.update(map_scope_valid=True, map_scope_reason='active_file_matches_live_map')
        except Exception as exc:
            result['map_scope_reason'] = 'active_map_unverified: ' + str(exc)[:160]
        return result

    def _observation_area(self, x, y, scope):
        """Name robot observation area; do not claim object is inside that room."""
        import yaml
        base = Path(self.node.workspace) / 'common/config' / 'semantic' / scope['floor_id']
        try:
            manifest = yaml.safe_load((base / 'map_manifest.yaml').read_text(encoding='utf-8')) or {}
            if manifest.get('floor_id') != scope['floor_id']:
                return None
            areas = self._read_json(base / manifest.get('semantic_areas', 'semantic_areas.geojson'))
            for feature in areas.get('features', []):
                props, geom = feature.get('properties', {}), feature.get('geometry', {})
                if (props.get('floor_id') != scope['floor_id'] or props.get('area_type') in (None, 'general')
                        or geom.get('type') != 'Polygon'):
                    continue
                rings = geom.get('coordinates', [])
                if rings and _inside_ring(x, y, rings[0]) and not any(_inside_ring(x, y, r) for r in rings[1:]):
                    return dict(name=props.get('display_name') or props.get('id'), id=props.get('id'),
                                source='room_polygon', floor_id=scope['floor_id'], map_id=scope['map_id'])
        except Exception:
            manifest = {}
        try:
            doc = yaml.safe_load((base / manifest.get('poi_database', 'pois.yaml')).read_text(encoding='utf-8')) or {}
            candidates = []
            for wp in doc.get('pois', []):
                if (not wp.get('enabled', True) or wp.get('floor_id') != scope['floor_id']
                        or wp.get('map_version') != manifest.get('map_version')):
                    continue
                distance = math.hypot(x - float(wp['x']), y - float(wp['y']))
                name = str(wp.get('display_name') or '').strip()
                if distance <= 1.2 and name and name != wp.get('id'):
                    candidates.append((distance, name, wp.get('id')))
            if candidates:
                distance, name, key = min(candidates)
                return dict(name=name + '附近', waypoint_name=name, id=key, source='nearest_waypoint',
                            distance_m=round(distance, 3), floor_id=scope['floor_id'], map_id=scope['map_id'])
        except Exception:
            pass
        return None

    def snapshot(self, captured_at):
        now, wall = time.monotonic(), time.time()
        result = dict(captured_at=captured_at, stationary=False, map_from_base=None,
                      map_pose_status='unavailable', localization_valid=False,
                      localization_status='amcl_unavailable', observation_area=None, area_hint=None,
                      motion=dict(linear_mps=None, angular_rps=None, fresh=False))
        result.update(self.map_scope())
        result['navigation_active'] = getattr(self.node, 'nx_handle', None) is not None
        odom = self.odom
        if odom is not None:
            age = wall - _stamp(odom)
            v = odom.twist.twist
            fresh = now - self.odom_received < .5 and -.1 < age < .5
            linear, angular = math.hypot(v.linear.x, v.linear.y), abs(v.angular.z)
            fresh = fresh and math.isfinite(linear) and math.isfinite(angular)
            result.update(odom_age_s=age, odom_received_age_s=now - self.odom_received)
            result['motion'] = dict(linear_mps=linear, angular_rps=angular, fresh=fresh,
                                    vx_mps=v.linear.x, vy_mps=v.linear.y, wz_rps=v.angular.z)
            result['stationary'] = bool(fresh and self.still_since is not None and now - self.still_since > .7)
        if not isinstance(captured_at, (int, float)) or not math.isfinite(captured_at) or abs(wall - captured_at) > 2:
            result['map_pose_status'] = 'capture_timestamp_stale'
            return result
        relocalizing = bool(getattr(getattr(self.node, 'relocalization', None), 'running', False))
        if relocalizing:
            self.relocalized_at = wall
        amcl = self.amcl
        result['localization_refresh_requested'] = False
        if not relocalizing:
            result['localization_refresh_requested'] = self._maybe_refresh_localization(
                result, wall - _stamp(amcl) if amcl is not None else float('inf'), now)
        if amcl is not None:
            age = wall - _stamp(amcl)
            covariance_info = normalize_planar_covariance(amcl.pose.covariance)
            sigma = covariance_info.pop('sigma')
            result['localization'] = dict(age_s=age, received_age_s=now - self.amcl_received,
                                           sigma_x_m=sigma[0] if sigma else None,
                                           sigma_y_m=sigma[1] if sigma else None,
                                           sigma_yaw_rad=sigma[2] if sigma else None,
                                           **covariance_info)
            age_limit = 30. if result['stationary'] else 5.
            if amcl.header.frame_id.lstrip('/') != 'map':
                status = 'amcl_wrong_frame'
            elif not -.1 < age < age_limit or now - self.amcl_received > age_limit:
                status = 'amcl_stale'
            elif not sigma or max(sigma[:2]) > .5 or sigma[2] > math.radians(25):
                status = 'amcl_uncertain'
            elif relocalizing or wall - self.relocalized_at < 2. or _stamp(amcl) < max(self.relocalized_at, self.map_changed_at):
                status = 'relocalizing_or_map_changed'
            elif not result['motion']['fresh']:
                status = 'odometry_stale'
            elif not result['map_scope_valid']:
                status = 'map_scope_unverified'
            else:
                status = 'amcl_quality_passed'
            result['localization_status'] = status
            # A tight AMCL covariance is internal particle agreement, not proof
            # that the estimated pose agrees with the physical map. Require a
            # separate current-scan/static-map consistency check as well.
            relocalizer = getattr(self.node, 'relocalization', None)
            alignment = relocalizer.alignment() if relocalizer else None
            result['scan_map'] = alignment
            if status == 'amcl_quality_passed' and (not alignment or not alignment.get('valid')):
                status = 'scan_map_unverified' if not alignment else alignment.get('reason', 'scan_map_mismatch')
                result['localization_status'] = status
            result['localization_valid'] = status == 'amcl_quality_passed'
        try:
            tf = self.buffer.lookup_transform('map', 'base_link', Time(seconds=captured_at), timeout=Duration(seconds=.3))
            t, q = tf.transform.translation, tf.transform.rotation
            values = [t.x, t.y, t.z, q.x, q.y, q.z, q.w]
            if not all(math.isfinite(v) for v in values):
                raise ValueError('nonfinite_transform')
            # Existing consumers must also fail closed on cached TF + poor pose.
            if result['localization_valid']:
                result['map_from_base'] = dict(translation=values[:3], quaternion_xyzw=values[3:])
                result['map_pose_status'] = 'tf_at_capture_time'
                result['observation_area'] = self._observation_area(t.x, t.y, result)
                if result['observation_area']:
                    result['area_hint'] = result['observation_area']['name']
            else:
                result['map_pose_status'] = result['localization_status']
        except Exception as exc:
            result['map_pose_status'] = str(exc)[:240]
            result['localization_valid'] = False
        return result
