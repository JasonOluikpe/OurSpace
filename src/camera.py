import math

from panda3d.core import Vec3


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def damp(current: Vec3, target: Vec3, speed: float, dt: float) -> Vec3:
    """Frame-rate-independent exponential approach."""
    if dt <= 0.0:
        return Vec3(current)
    alpha = 1.0 - math.exp(-speed * dt)
    return current + (target - current) * alpha


class FollowCamera:
    def __init__(self, app, target, world=None, *,
        yaw: float = 45.0,
        pitch: float = 50.0,
        distance: float = 26.0,
        min_distance: float = 10.0,
        max_distance: float = 32.0,
        min_pitch: float = 30.0,
        max_pitch: float = 75.0,
        follow_speed: float = 14.0,
        look_speed: float = 18.0,
        mouse_sensitivity: float = 140.0,
        target_height: float = 1.05,
    ) -> None:
        self.app = app
        self.camera = app.camera
        self.target = target
        self.world = world

        self.yaw = yaw
        self.pitch = pitch
        self.distance = distance
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.min_pitch = min_pitch
        self.max_pitch = max_pitch
        self.follow_speed = follow_speed
        self.look_speed = look_speed
        self.mouse_sensitivity = mouse_sensitivity
        self.target_height = target_height

        self._dragging = False
        self._last_mouse: tuple[float, float] | None = None
        self._position: Vec3 | None = None
        self._look_target: Vec3 | None = None

        self.app.camLens.setFov(55.0)
        self.app.camLens.setNearFar(0.1, 500.0)

        app.accept("mouse3", self._start_drag)
        app.accept("mouse3-up", self._stop_drag)
        app.accept("wheel_up", self._zoom, [-1.0])
        app.accept("wheel_down", self._zoom, [1.0])

        self.snap()

    # ------------------------------------------------------------------ input
    def _start_drag(self) -> None:
        self._dragging = True
        self._last_mouse = None

    def _stop_drag(self) -> None:
        self._dragging = False
        self._last_mouse = None

    def _zoom(self, amount: float) -> None:
        self.distance = clamp(self.distance + amount, self.min_distance, self.max_distance)

    # ------------------------------------------------------------------ camera
    def _target_point(self) -> Vec3:
        return self.target.getPos(self.app.render) + Vec3(0.0, 0.0, self.target_height)

    def _desired_position(self, look_target: Vec3) -> Vec3:
        yaw = math.radians(self.yaw)
        pitch = math.radians(self.pitch)
        horizontal = self.distance * math.cos(pitch)

        # yaw=0 puts the camera behind a +Y-facing player, looking toward +Y.
        forward = Vec3(math.sin(yaw), math.cos(yaw), 0.0)
        desired = look_target - forward * horizontal
        desired.z += self.distance * math.sin(pitch)

        if self.world is not None:
            floor = self.world.height_at(desired.x, desired.y) + 1.0
            desired.z = max(desired.z, floor)
        return desired

    def _read_mouse(self) -> None:
        if not self._dragging:
            self._last_mouse = None
            return

        mouse = self.app.mouseWatcherNode
        if not mouse.hasMouse():
            self._last_mouse = None
            return

        current = (mouse.getMouseX(), mouse.getMouseY())
        if self._last_mouse is not None:
            dx = current[0] - self._last_mouse[0]
            dy = current[1] - self._last_mouse[1]
            self.yaw = (self.yaw - dx * self.mouse_sensitivity + 180.0) % 360.0 - 180.0
            self.pitch = clamp(self.pitch + dy * self.mouse_sensitivity, self.min_pitch, self.max_pitch)
        self._last_mouse = current

    def snap(self) -> None:
        self._look_target = self._target_point()
        self._position = self._desired_position(self._look_target)
        self.camera.setPos(self._position)
        self.camera.lookAt(self._look_target, Vec3(0.0, 0.0, 1.0))

    def update(self, dt: float) -> None:
        self._read_mouse()

        target = self._target_point()
        if self._look_target is None:
            self._look_target = target
        else:
            self._look_target = damp(self._look_target, target, self.look_speed, dt)

        desired = self._desired_position(self._look_target)
        if self._position is None:
            self._position = desired
        else:
            self._position = damp(self._position, desired, self.follow_speed, dt)

        self.camera.setPos(self._position)
        self.camera.lookAt(self._look_target, Vec3(0.0, 0.0, 1.0))
