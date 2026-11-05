import math
from panda3d.core import Vec3


def delta_angle(current: float, target: float) -> float:
    return (target - current + 180.0) % 360.0 - 180.0

def move_towards(current: float, target: float, max_delta: float) -> float:
    if abs(target - current) <= max_delta:
        return target
    return current + math.copysign(max_delta, target - current)

def move_towards_angle(current: float, target: float, max_delta: float) -> float:
    delta = delta_angle(current, target)
    return current + math.copysign(min(abs(delta), max_delta), delta)

def smooth_damp(current: float, target: float, velocity: float, smooth_time: float, dt: float) -> tuple[float, float]:
    smooth_time = max(0.0001, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * exp
    output = target + (change + temp) * exp

    if (target - current > 0.0) == (output > target):
        output = target
        velocity = (output - target) / dt if dt > 0.0 else 0.0
    return output, velocity

def smooth_damp_angle(current: float, target: float, velocity: float, smooth_time: float, dt: float) -> tuple[float, float]:
    return smooth_damp(current, current + delta_angle(current, target), velocity, smooth_time, dt)

def smooth_damp_vec3(current: Vec3, target: Vec3, velocity: Vec3, smooth_time: float, dt: float) -> tuple[Vec3, Vec3]:
    axes = [smooth_damp(c, t, v, smooth_time, dt) for c, t, v in zip(current, target, velocity)]
    return Vec3(*(a[0] for a in axes)), Vec3(*(a[1] for a in axes))

def rotate_yaw(vector: Vec3, yaw_degrees: float) -> Vec3:
    angle = math.radians(yaw_degrees)
    c, s = math.cos(angle), math.sin(angle)
    return Vec3(vector.x * c + vector.y * s, -vector.x * s + vector.y * c, vector.z)

def dir_from_yaw(yaw_deg: float) -> Vec3:
    a = math.radians(yaw_deg)
    return Vec3(math.sin(a), math.cos(a), 0.0)

def yaw_from_dir(x: float, y: float) -> float:
    return math.degrees(math.atan2(x, y))
