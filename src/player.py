from __future__ import annotations

import math
import time
from typing import Optional

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    Material,
    Plane,
    Point3,
    Vec3,
    Vec4,
)

from .displacement import (
    Dash,
    DashDirection,
    DewEase,
    DispByDestination,
    DispByTarget,
    Displacement,
)
from .gamepad import Gamepad
from .mathutil import (
    delta_angle,
    dir_from_yaw,
    move_towards,
    move_towards_angle,
    rotate_yaw,
    smooth_damp_angle,
    yaw_from_dir,
)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def make_capsule(radius: float, height: float, segments: int = 20, cap_rings: int = 8):
    """Create a smooth-shaded, Z-up capsule GeomNode.

    The base is at z=0, the top is at z=height.  The straight side runs from
    z=radius to z=height-radius; both caps are hemispheres.
    """
    fmt = GeomVertexFormat.getV3n3()
    vdata = GeomVertexData("player-capsule", fmt, Geom.UHStatic)
    vwriter = GeomVertexWriter(vdata, "vertex")
    nwriter = GeomVertexWriter(vdata, "normal")
    prim = GeomTriangles(Geom.UHStatic)

    # (z, ring radius, normal z, normal radial)
    rows: list[tuple[float, float, float, float]] = []
    for i in range(cap_rings + 1):
        phi = -math.pi / 2.0 + (math.pi / 2.0) * i / cap_rings
        rows.append(
            (
                radius + radius * math.sin(phi),
                radius * math.cos(phi),
                math.sin(phi),
                math.cos(phi),
            )
        )
    rows.append((height - radius, radius, 0.0, 1.0))
    for i in range(1, cap_rings + 1):
        phi = (math.pi / 2.0) * i / cap_rings
        rows.append(
            (
                height - radius + radius * math.sin(phi),
                radius * math.cos(phi),
                math.sin(phi),
                math.cos(phi),
            )
        )

    next_index = 0
    ring_indices: list[list[int]] = []
    for z, ring_radius, nz, nr in rows:
        if ring_radius < 1e-6:
            vwriter.addData3(0.0, 0.0, z)
            nwriter.addData3(0.0, 0.0, nz)
            ring_indices.append([next_index])
            next_index += 1
            continue

        indices = []
        for j in range(segments):
            theta = 2.0 * math.pi * j / segments
            ct, st = math.cos(theta), math.sin(theta)
            vwriter.addData3(ring_radius * ct, ring_radius * st, z)
            nwriter.addData3(nr * ct, nr * st, nz)
            indices.append(next_index)
            next_index += 1
        ring_indices.append(indices)

    for r in range(len(ring_indices) - 1):
        lower = ring_indices[r]
        upper = ring_indices[r + 1]

        if len(lower) == 1 and len(upper) > 1:
            for j in range(segments):
                prim.addVertices(lower[0], upper[(j + 1) % segments], upper[j])
        elif len(lower) > 1 and len(upper) == 1:
            for j in range(segments):
                prim.addVertices(lower[j], lower[(j + 1) % segments], upper[0])
        else:
            for j in range(segments):
                jn = (j + 1) % segments
                prim.addVertices(lower[j], lower[jn], upper[jn])
                prim.addVertices(lower[j], upper[jn], upper[j])

    prim.closePrimitive()
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode("player-capsule")
    node.addGeom(geom)
    return node


# ---------------------------------------------------------------------------
# Player / EntityControl
# ---------------------------------------------------------------------------

class Player:
    """The player entity: movement, input, dash and displacement."""

    def __init__(self, app, world) -> None:
        self.app = app
        self.world = world

        # --- EntityControl defaults recovered from Dew.Core
        self.base_agent_speed = 5.0
        self.normalized_acceleration = 4.0
        self.rotate_speed = 720.0
        self.rotation_smooth_time = 0.05
        self.is_hero = True

        # --- stats (FinalStats.movementSpeedMultiplier)
        self.movement_speed_multiplier = 1.0
        self.max_health = 100.0
        self.health = 100.0
        self.disable_damage_overlay = False

        # --- crowd control
        self.is_rooted = False
        self.is_stunned = False
        self.has_crowd_control_immunity = False

        # --- movement state
        self.local_velocity = Vec3(0.0, 0.0, 0.0)
        self.speed = 0.0
        self.vel_yaw = 0.0
        self.body_yaw = 0.0
        self._body_yaw_vel = 0.0

        # Directional input (WASD / stick) is a vector of length <= 1;
        # destination input (mouse) is a point.  At most one is active.
        self._movement_vector: Optional[Vec3] = None
        self._destination: Optional[Vec3] = None

        # --- ControlManager tuning
        self.continuous_move_dispatch_interval = 0.0625
        self._mouse_held = False
        self._last_mouse_dispatch = -1e9

        self._attack_slow_start = -1e9
        self._attack_slow_duration = 0.0

        # --- dash
        self.dash_distance = 2.25
        self.dash_duration = 0.25
        self.dash_ease = DewEase.Linear
        self.dash_cooldown = 0.6          # ability data, not in the DLL
        self._dash_cooldown = 0.0

        # --- displacement
        self.displacement: Optional[Displacement] = None
        self._disp_start = Vec3(0.0, 0.0, 0.0)

        # --- scene
        self.node = app.render.attachNewNode("player")
        self.node.setPos(world.spawn.x, world.spawn.y, world.spawn.z)

        self.model = self.node.attachNewNode(make_capsule(radius=0.4, height=1.8))
        self.model.setTwoSided(True)

        material = Material()
        material.setDiffuse(Vec4(0.88, 0.07, 0.06, 1.0))
        material.setAmbient(Vec4(0.30, 0.02, 0.02, 1.0))
        material.setSpecular(Vec4(0.45, 0.16, 0.14, 1.0))
        material.setShininess(28.0)
        self.model.setMaterial(material, 1)

        self._bind_input()

    # ------------------------------------------------------------------ input
    def _bind_input(self) -> None:
        self._keys = {"forward": False, "back": False, "left": False, "right": False}
        for key, action in (("w", "forward"), ("s", "back"),
                            ("a", "left"), ("d", "right")):
            self.app.accept(key, self._set_key, [action, True])
            self.app.accept(key + "-up", self._set_key, [action, False])

        self.app.accept("space", self._try_dash, [DashDirection.AllTowardsCursor])
        self.app.accept("mouse1", self._set_mouse_held, [True])
        self.app.accept("mouse1-up", self._set_mouse_held, [False])

        # PS4 controller: left stick moves, Cross dashes the way you move.
        self.gamepad = Gamepad(
            self.app, lambda: self._try_dash(DashDirection.CurrentMovement))

        # Small demo hooks for systems without an attack/damage source here.
        self.app.accept("f", self.set_attack_move_slow, [0.35])
        self.app.accept("k", self._simulate_knockback)
        self.app.accept("h", self.take_damage, [10.0])
        self.app.accept("j", self.heal, [20.0])

    def _set_key(self, action: str, pressed: bool) -> None:
        self._keys[action] = pressed

    def _set_mouse_held(self, held: bool) -> None:
        self._mouse_held = held
        if held:
            self._last_mouse_dispatch = -1e9

    def _simulate_knockback(self) -> None:
        self.apply_knockback(-dir_from_yaw(self.body_yaw), distance=1.6, duration=0.22)

    # ------------------------------------------------------------------ queries
    @property
    def agent_position(self) -> Vec3:
        return self.node.getPos(self.app.render)

    @property
    def current_max_agent_speed(self) -> float:
        return (self.base_agent_speed
                * max(0.0, self.movement_speed_multiplier)
                * self._attack_move_multiplier())

    @property
    def is_displacing(self) -> bool:
        return self.displacement is not None

    @property
    def is_dashing(self) -> bool:
        return self.displacement is not None and self.displacement.is_friendly

    def _attack_move_multiplier(self) -> float:
        duration = self._attack_slow_duration
        if duration <= 0.0:
            return 1.0
        elapsed = time.monotonic() - self._attack_slow_start
        if elapsed >= duration:
            return 1.0
        return 0.5 + 0.5 * (elapsed / duration)

    def set_attack_move_slow(self, duration: float) -> None:
        """``SetAttackMovSpdDisadvantage_Imp``."""
        self._attack_slow_start = time.monotonic()
        self._attack_slow_duration = max(0.0, duration) * 2.0

    def take_damage(self, amount: float) -> None:
        self.health = max(0.0, self.health - max(0.0, amount))

    def heal(self, amount: float) -> None:
        self.health = min(self.max_health, self.health + max(0.0, amount))

    # ------------------------------------------------------------------ cursor
    def _cursor_ground_point(self) -> Optional[Vec3]:
        mouse = self.app.mouseWatcherNode
        if not mouse or not mouse.hasMouse():
            return None
        near, far = Point3(), Point3()
        self.app.camLens.extrude(mouse.getMouse(), near, far)
        near = self.app.render.getRelativePoint(self.app.camera, near)
        far = self.app.render.getRelativePoint(self.app.camera, far)
        hit = Point3()
        plane = Plane(Vec3(0.0, 0.0, 1.0), Point3(0.0, 0.0, 0.0))
        if not plane.intersectsLine(hit, near, far):
            return None
        return Vec3(hit.x, hit.y, 0.0)

    def _clamp_to_play_area(self, point: Vec3) -> Vec3:
        radius = math.hypot(point.x, point.y)
        limit = self.world.play_radius
        if radius > limit and radius > 1e-8:
            scale = limit / radius
            point.x *= scale
            point.y *= scale
        point.z = self.world.height_at(point.x, point.y)
        return point

    def project_destination(self, start: Vec3, target: Vec3,
                            use_linear_sweep: bool = True,
                            can_go_over_terrain: bool = False) -> Vec3:
        """Stand-in for Dew.GetValidAgentDestination_LinearSweep/Closest."""
        limit = self.world.play_radius
        end = Vec3(target)
        if end.x * end.x + end.y * end.y <= limit * limit:
            return self._clamp_to_play_area(end)

        if use_linear_sweep and not can_go_over_terrain:
            direction = end - start
            a = direction.x * direction.x + direction.y * direction.y
            if a < 1e-8:
                return self._clamp_to_play_area(Vec3(start))
            b = 2.0 * (start.x * direction.x + start.y * direction.y)
            c = start.x * start.x + start.y * start.y - limit * limit
            discriminant = b * b - 4.0 * a * c
            if discriminant <= 0.0:
                return self._clamp_to_play_area(Vec3(start))
            t = (-b + math.sqrt(discriminant)) / (2.0 * a)
            result = start + direction * max(0.0, min(1.0, t))
        else:
            length = math.hypot(end.x, end.y)
            result = Vec3(0.0, 0.0, 0.0) if length < 1e-8 else Vec3(
                end.x * limit / length, end.y * limit / length, 0.0)

        return self._clamp_to_play_area(result)

    # ------------------------------------------------------------------ input logic
    def _read_directional_input(self) -> tuple[float, float]:
        """Left stick if it is active, otherwise WASD.  Length <= 1."""
        stick = self.gamepad.stick()
        if stick != (0.0, 0.0):
            return stick
        ix = (1.0 if self._keys["right"] else 0.0) - (1.0 if self._keys["left"] else 0.0)
        iy = (1.0 if self._keys["forward"] else 0.0) - (1.0 if self._keys["back"] else 0.0)
        length = math.hypot(ix, iy)
        return (ix / length, iy / length) if length > 1.0 else (ix, iy)

    def _process_input(self, now: float, camera_yaw: float) -> None:
        # The game checks the move trigger first; mouse movement wins while held.
        if self._mouse_held:
            if now - self._last_mouse_dispatch >= self.continuous_move_dispatch_interval:
                self._last_mouse_dispatch = now
                hit = self._cursor_ground_point()
                if hit is not None:
                    self._destination = self._clamp_to_play_area(hit)
                    self._movement_vector = None
            return

        ix, iy = self._read_directional_input()
        strength = math.hypot(ix, iy)
        if strength > 0.0:
            # Camera-relative input: entityCamAngleRotation * (x, 0, y), with
            # the game's 0.4 + 0.6 * strength speed curve.
            wish = rotate_yaw(Vec3(ix, iy, 0.0), camera_yaw) / strength
            self._movement_vector = wish * (0.4 + 0.6 * strength)
            self._destination = None
        else:
            self._movement_vector = None      # ClearMovement()

    # ------------------------------------------------------------------ movement
    def _do_movement_processor_frame_update(self, dt: float, pos: Vec3) -> None:
        target_velocity = Vec3(0.0, 0.0, 0.0)

        if self._movement_vector is not None:
            target_velocity = self._movement_vector * self.current_max_agent_speed
        elif self._destination is not None:
            delta = self._destination - pos
            delta.z = 0.0
            distance = delta.length()
            if distance <= max(0.1, self.local_velocity.length() * dt):
                self._destination = None
            else:
                target_velocity = delta * (self.current_max_agent_speed / distance)

        velocity = self._do_velocity_update(target_velocity, dt)
        self.node.setPos(self._clamp_to_play_area(pos + velocity * dt))

        if self.speed > 0.1:
            difference = abs(delta_angle(self.body_yaw, self.vel_yaw))
            smoothing = self.rotation_smooth_time * (2.0 if difference < 60.0 else 1.0)
            self.body_yaw, self._body_yaw_vel = smooth_damp_angle(
                self.body_yaw, self.vel_yaw, self._body_yaw_vel, smoothing, dt)
            self.node.setH(-self.body_yaw)

    def _do_velocity_update(self, target_velocity: Vec3, dt: float) -> Vec3:
        current_speed = self.local_velocity.length()
        target_speed = target_velocity.length()
        max_speed = self.current_max_agent_speed

        if max_speed < 0.1 or target_speed <= 1e-6:
            acceleration = min(max(self.base_agent_speed, 0.1), 1000.0) * 5.0
        else:
            acceleration = self.normalized_acceleration * max_speed

        rate = acceleration * dt * (2.0 if current_speed > target_speed else 1.0)
        self.speed = move_towards(current_speed, target_speed, rate)

        if target_speed > 1e-6:
            self.vel_yaw = move_towards_angle(
                self.vel_yaw, yaw_from_dir(target_velocity.x, target_velocity.y),
                self.rotate_speed * max(0.0, self.movement_speed_multiplier) * dt)

        self.local_velocity = dir_from_yaw(self.vel_yaw) * self.speed
        return self.local_velocity

    # ------------------------------------------------------------------ dash
    def _dash_direction_vector(self, mode: DashDirection) -> Vec3:
        """Aim of a dash: the cursor, else the way we are moving, else facing."""
        pos = self.agent_position
        candidates = []
        if mode == DashDirection.AllTowardsCursor:
            candidates.append(self._cursor_ground_point())
        if self._movement_vector is not None:
            candidates.append(pos + self._movement_vector)
        candidates.append(self._destination)

        for point in candidates:
            if point is None:
                continue
            delta = point - pos
            delta.z = 0.0
            if delta.lengthSquared() > 1e-6:
                return delta.normalized()
        return dir_from_yaw(self.body_yaw)

    def _try_dash(self, mode: DashDirection) -> None:
        if self.is_displacing or self._dash_cooldown > 0.0:
            return
        Dash(
            distance=self.dash_distance,
            duration=self.dash_duration,
            ease=self.dash_ease,
        ).apply_by_direction(self, self._dash_direction_vector(mode))
        self._dash_cooldown = self.dash_cooldown

    # ------------------------------------------------------------------ displacement
    def start_displacement(self, displacement: Displacement) -> None:
        if displacement is None or not displacement.is_alive:
            return
        # Enemy-applied movement is refused by crowd-control immunity.
        if not displacement.is_friendly and self.has_crowd_control_immunity:
            displacement.cancel()
            return
        if self.displacement is not None:
            self.cancel_displacement()

        displacement.start()
        self.displacement = displacement
        self._disp_start = self.agent_position
        self.speed = 0.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)

    def cancel_displacement(self) -> None:
        displacement, self.displacement = self.displacement, None
        if displacement is not None:
            displacement.cancel()

    def _finish_displacement(self) -> None:
        displacement, self.displacement = self.displacement, None
        if displacement is None:
            return
        displacement.finish()
        self.speed = 0.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)

    def _do_displacement(self, displacement: Displacement, dt: float, pos: Vec3) -> None:
        # DoDisplacement cancels when crowd control lands on the entity.
        if displacement.is_canceled_by_cc and (self.is_rooted or self.is_stunned):
            self.cancel_displacement()
            return

        displacement.elapsed_time += dt
        multiplier = 1.0
        if displacement.affected_by_movement_speed:
            multiplier = max(0.0, self.movement_speed_multiplier)
            if self.is_hero:
                multiplier = min(multiplier, 2.5)

        if isinstance(displacement, DispByDestination):
            duration = max(1e-5, displacement.duration)
            target = displacement.position_at(
                self._disp_start, displacement.elapsed_time / duration, multiplier)
            finished = displacement.elapsed_time >= duration
        elif isinstance(displacement, DispByTarget):
            target = displacement.step(pos, dt, multiplier)
            finished = displacement.has_reached(target) or (
                displacement.cancel_time > 0.0
                and displacement.elapsed_time >= displacement.cancel_time)
        else:
            self._finish_displacement()
            return

        target = self._clamp_to_play_area(target)
        if displacement.rotate_forward:
            self._set_body_yaw_from_direction(
                target - pos, displacement.rotate_smoothly, dt)

        self.node.setPos(target)
        if finished:
            self._finish_displacement()

    def _set_body_yaw_from_direction(self, direction: Vec3, smooth: bool,
                                     dt: float) -> None:
        if direction.lengthSquared() < 1e-8:
            return
        target = yaw_from_dir(direction.x, direction.y)
        if smooth:
            self.body_yaw, self._body_yaw_vel = smooth_damp_angle(
                self.body_yaw, target, self._body_yaw_vel,
                self.rotation_smooth_time, dt)
        else:
            self.body_yaw = target
            self._body_yaw_vel = 0.0
        self.node.setH(-self.body_yaw)

    def apply_knockback(self, direction: Vec3, distance: float = 1.5,
                        duration: float = 0.25, on_finish=None) -> DispByDestination:
        heading = Vec3(direction)
        heading.z = 0.0
        if heading.lengthSquared() < 1e-8:
            heading = dir_from_yaw(self.body_yaw)
        heading.normalize()

        start = self.agent_position
        displacement = DispByDestination(
            duration=max(1e-5, duration),
            ease=DewEase.EaseOutQuad,
            destination=self.project_destination(
                start, start + heading * max(0.0, distance)),
            is_friendly=False,
            is_canceled_by_cc=True,
            rotate_forward=False,
            on_finish=on_finish,
        )
        self.start_displacement(displacement)
        return displacement

    # ------------------------------------------------------------------ update
    def update(self, dt: float, camera_yaw: float) -> None:
        if dt <= 0.0:
            return

        self._dash_cooldown = max(0.0, self._dash_cooldown - dt)
        self._process_input(time.monotonic(), camera_yaw)

        pos = self.agent_position
        if self.displacement is not None:
            self._do_displacement(self.displacement, dt, pos)
        else:
            self._do_movement_processor_frame_update(dt, pos)