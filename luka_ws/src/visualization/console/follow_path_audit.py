"""Conservative read-only swept-footprint audit for short follow paths.

The input is a Nav2 GetCostmap response's ``map`` and a nav_msgs/Path. This
does not replace the local controller or collision monitor: it rejects a path
that is already unsafe in the current global costmap before it can be sent to
the controller.
"""
import math


def yaw_of(pose):
    q = pose.orientation
    return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))


def path_audit(path, grid, max_length_m, max_turn_rad=1.2):
    poses = path.poses
    result = dict(safe=False, reason='路径无效', length_m=0., turn_rad=0.,
                  sampled=0, lethal=0, inscribed=0, unknown=0)
    if path.header.frame_id != 'map' or len(poses) < 2:
        return result
    info = grid.metadata
    resolution, width, height = info.resolution, info.size_x, info.size_y
    if not (math.isfinite(resolution) and 0.01 <= resolution <= .20 and
            width > 0 and height > 0 and len(grid.data) == width*height):
        result['reason'] = '代价地图无效'
        return result
    origin = info.origin.position
    previous = poses[0].pose
    if not all(math.isfinite(v) for v in (previous.position.x, previous.position.y, yaw_of(previous))):
        return result
    # Global and local costmaps use a 0.56 x 0.38 m body with 0.03 m padding.
    # Sample more densely than half a costmap cell. Cost 253 is the inflated
    # inscribed buffer, not an occupied obstacle cell; retain it as a warning.
    pitch = min(.02, resolution/2)
    cells_x, cells_y = math.ceil(.31/pitch), math.ceil(.22/pitch)
    for current_stamped in poses:
        current = current_stamped.pose
        x, y, yaw = current.position.x, current.position.y, yaw_of(current)
        if not all(math.isfinite(v) for v in (x, y, yaw)):
            result['reason'] = '路径坐标无效'
            return result
        dx, dy = x-previous.position.x, y-previous.position.y
        turn = math.atan2(math.sin(yaw-yaw_of(previous)),
                          math.cos(yaw-yaw_of(previous)))
        result['length_m'] += math.hypot(dx, dy)
        result['turn_rad'] += abs(turn)
        if (result['length_m'] > max_length_m or
                result['turn_rad'] > max_turn_rad):
            result['reason'] = '路径过长或转向过大'
            return result
        steps = max(1, math.ceil(math.hypot(dx, dy)/.025),
                    math.ceil(abs(turn)/math.radians(5)))
        for step in range(steps+1):
            fraction = step/steps
            px = previous.position.x+dx*fraction
            py = previous.position.y+dy*fraction
            pyaw = yaw_of(previous)+turn*fraction
            c, s = math.cos(pyaw), math.sin(pyaw)
            result['sampled'] += 1
            for xi in range(-cells_x, cells_x+1):
                fx = .31*xi/cells_x
                for yi in range(-cells_y, cells_y+1):
                    fy = .22*yi/cells_y
                    gx = math.floor((px+fx*c-fy*s-origin.x)/resolution)
                    gy = math.floor((py+fx*s+fy*c-origin.y)/resolution)
                    if not (0 <= gx < width and 0 <= gy < height):
                        result['unknown'] += 1
                        result['reason'] = '路径越出已知地图'
                        return result
                    cost = grid.data[gy*width+gx]
                    if cost == 255:
                        result['unknown'] += 1
                        result['reason'] = '路径经过未知区域'
                        return result
                    if cost == 254:
                        result['lethal'] += 1
                        result['reason'] = '车身扫掠触及障碍'
                        return result
                    if cost == 253:
                        result['inscribed'] += 1
        previous = current
    result['safe'] = True
    result['reason'] = ('车身未触障，但进入膨胀缓冲区' if result['inscribed']
                        else '完整车身路径安全')
    return result
