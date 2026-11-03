"""Player movement modelled on Shape of Dreams' ``EntityControl``.

Everything here comes from the REA notes on ``Dew.Core``:

* ``EntityControl`` runs a NavMeshAgent in the real game; this project uses
  the same velocity maths directly on the player node.
* ``baseAgentSpeed = 5``, ``normalizedAcceleration = 4``,
  ``rotateSpeed = 720`` deg/s, ``rotationSmoothTime = 0.05``.
* Acceleration is ``normalizedAcceleration * maxSpeed`` (doubled while
  slowing down); stopping uses ``clamp(baseSpeed, 0.1, 1000) * 5``.
* Attacks slow movement to 0.5x, lerping back to 1x over ``duration * 2``.
* Directional input is camera-relative and uses the game's
  ``0.4 + 0.6 * strength`` walk-strength curve.
* Dashing is a ``DispByDestination``: 2.25 units over 0.25 s (9 units/s).

Controls
--------
* WASD           - camera-relative movement
* Left mouse     - click/hold to move to the cursor (destination mode)
* Space          - dash in the current movement direction
* F              - fake attack, triggers the attack movement slow
* K              - take a knockback (demonstrates displacement)
* H / J          - take 10 damage / heal 20 (drives the camera vignette)

Not applicable here: Mirror networking, NavMesh obstacle avoidance (the
arena is flat and open) and the animation parameter layer.
"""

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


# ---------------------------------------------------------------------------
# Geometry / maths helpers
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


def delta_angle(current: float, target: float) -> float:
    return (target - current + 180.0) % 360.0 - 180.0


def move_towards(current: float, target: float, max_delta: float) -> float:
    if abs(target - current) <= max_delta:
        return target
    return current + math.copysign(max_delta, target - current)


def move_towards_angle(current: float, target: float, max_delta: float) -> float:
    d = delta_angle(current, target)
    if abs(d) <= max_delta:
        return target
    return current + math.copysign(max_delta, d)


def smooth_damp_angle(current: float, target: float, velocity: float,
                      smooth_time: float, dt: float) -> tuple[float, float]:
    target = current + delta_angle(current, target)
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


def dir_from_yaw(yaw_deg: float) -> Vec3:
    """Yaw 0 = +Y, yaw 90 = +X (same convention as the camera)."""
    a = math.radians(yaw_deg)
    return Vec3(math.sin(a), math.cos(a), 0.0)


def yaw_from_dir(x: float, y: float) -> float:
    return math.degrees(math.atan2(x, y))


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
        self.outer_radius = 0.45
        self.inner_radius = 0.25
        self.obstacle_avoidance = True
        self.is_hero = True

        # --- stats (FinalStats.movementSpeedMultiplier)
        self.movement_speed_multiplier = 1.0
        self.max_health = 100.0
        self.health = 100.0
        self.disable_damage_overlay = False

        # --- movement state
        self.local_velocity = Vec3(0.0, 0.0, 0.0)
        self.speed = 0.0
        self.vel_yaw = 0.0
        self.body_yaw = 0.0
        self._body_yaw_vel = 0.0
        self._walk_strength = 0.0
        self.force_walking = False
        self.actions_blocked = False
        self.is_rooted = False
        self.is_stunned = False
        self.is_invulnerable = False
        self.is_unstoppable = False
        self.has_crowd_control_immunity = False

        self._movement_vector: Optional[Vec3] = None
        self._is_direction = False
        self._destination: Optional[Vec3] = None
        self._destination_speed_multiplier = 1.0

        # --- ControlManager tuning
        self.continuous_move_dispatch_interval = 0.0625
        self.directional_move_dispatch_interval = 1.0 / 60.0
        self.movement_direction_stale_time = 0.4
        self.min_walk_strength_for_gamepads = 0.0
        self._last_movement_direction = Vec3(0.0, 1.0, 0.0)
        self._last_movement_strength = 0.0
        self._last_movement_direction_time = -1e9
        self._mouse_held = False
        self._last_mouse_dispatch = -1e9

        # --- attack movement slow
        self._attack_slow_start = -1e9
        self._attack_slow_duration = 0.0

        # --- dash
        self.dash_distance = 2.25
        self.dash_duration = 0.25
        self.dash_ease = DewEase.Linear
        self.dash_direction = DashDirection.CurrentMovement
        self.dash_cooldown = 0.6          # ability data, not in the DLL
        self._dash_cooldown = 0.0

        # --- displacement
        self.displacement: Optional[Displacement] = None
        self._disp_start = Vec3(0.0, 0.0, 0.0)

        # --- scene
        self.node = app.render.attachNewNode("player")
        self.node.setPos(world.spawn.x, world.spawn.y, world.spawn.z)

        capsule = make_capsule(radius=0.4, height=1.8)
        self.model = self.node.attachNewNode(capsule)
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

        self.app.accept("space", self._try_dash)
        self.app.accept("mouse1", self._on_mouse_down)
        self.app.accept("mouse1-up", self._on_mouse_up)

        # Small demo hooks for systems without an attack/damage source here.
        self.app.accept("f", self._simulate_attack)
        self.app.accept("k", self._simulate_knockback)
        self.app.accept("h", self.take_damage, [10.0])
        self.app.accept("j", self.heal, [20.0])

    def _set_key(self, action: str, pressed: bool) -> None:
        self._keys[action] = pressed

    def _on_mouse_down(self) -> None:
        self._mouse_held = True
        self._last_mouse_dispatch = -1e9

    def _on_mouse_up(self) -> None:
        self._mouse_held = False

    def _simulate_attack(self) -> None:
        self.set_attack_move_slow(0.35)

    def _simulate_knockback(self) -> None:
        self.apply_knockback(-dir_from_yaw(self.body_yaw),
                             distance=1.6, duration=0.22)

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
    def walk_strength(self) -> float:
        return self._filter_walk_strength(self._walk_strength)

    @property
    def is_walking(self) -> bool:
        return self.walk_strength > 0.01

    @property
    def is_displacing(self) -> bool:
        return self.displacement is not None

    @property
    def is_dashing(self) -> bool:
        return self.displacement is not None and self.displacement.is_friendly

    @property
    def is_dodging(self) -> bool:
        return self.displacement is not None and self.displacement.is_dodging

    @property
    def is_last_movement_direction_fresh(self) -> bool:
        return (time.monotonic() - self._last_movement_direction_time
                < self.movement_direction_stale_time)

    @property
    def health_ratio(self) -> float:
        return self.health / self.max_health if self.max_health > 0.0 else 0.0

    def _filter_walk_strength(self, value: float) -> float:
        if self.force_walking:
            return 1.0
        if (self.actions_blocked or self.is_displacing
                or self.is_rooted or self.is_stunned):
            return 0.0
        if self.current_max_agent_speed < 0.1:
            return 0.0
        return value

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

    def set_movement_speed_multiplier(self, value: float) -> None:
        self.movement_speed_multiplier = max(0.0, value)

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
        point = mouse.getMouse()
        self.app.camLens.extrude(point, near, far)
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
            t = max(0.0, min(1.0, t))
            result = start + direction * t
        else:
            length = math.hypot(end.x, end.y)
            if length < 1e-8:
                result = Vec3(0.0, 0.0, 0.0)
            else:
                result = Vec3(end.x * limit / length, end.y * limit / length, 0.0)

        return self._clamp_to_play_area(result)

    # ------------------------------------------------------------------ input logic
    def _process_input(self, now: float, camera_yaw: float) -> None:
        # The game checks the move trigger first; mouse movement wins while held.
        if self._mouse_held:
            if now - self._last_mouse_dispatch >= self.continuous_move_dispatch_interval:
                self._last_mouse_dispatch = now
                hit = self._cursor_ground_point()
                if hit is not None:
                    self._destination = self._clamp_to_play_area(hit)
                    self._destination_speed_multiplier = 1.0
                    self._movement_vector = None
                    self._is_direction = False
            return

        ix = (1.0 if self._keys["right"] else 0.0) - (1.0 if self._keys["left"] else 0.0)
        iy = (1.0 if self._keys["forward"] else 0.0) - (1.0 if self._keys["back"] else 0.0)

        if ix != 0.0 or iy != 0.0:
            # Camera-relative input: entityCamAngleRotation * (x, 0, y).
            angle = math.radians(camera_yaw)
            forward = Vec3(math.sin(angle), math.cos(angle), 0.0)
            right = Vec3(math.cos(angle), -math.sin(angle), 0.0)
            wish = forward * iy + right * ix
            wish.normalize()

            self._last_movement_direction = Vec3(wish)
            self._last_movement_strength = 1.0
            self._last_movement_direction_time = now

            self._movement_vector = wish
            self._is_direction = True
            self._destination = None
            self._destination_speed_multiplier = 1.0
        elif self._is_direction:
            # Directional input released -> ClearMovement().
            self._movement_vector = None
            self._is_direction = False

    # ------------------------------------------------------------------ movement
    def _do_movement_processor_frame_update(self, dt: float, pos: Vec3) -> None:
        target_velocity = Vec3(0.0, 0.0, 0.0)
        target_walk = 0.0

        if self._is_direction and self._movement_vector is not None:
            magnitude = min(1.0, self._movement_vector.length())
            if magnitude > 1e-6:
                target_velocity = self._movement_vector * (
                    self.current_max_agent_speed / magnitude)
                target_walk = magnitude
        elif self._destination is not None:
            delta = self._destination - pos
            delta.z = 0.0
            distance = delta.length()
            if distance <= max(0.1, self.local_velocity.length() * dt):
                self._destination = None
            else:
                speed = (self.current_max_agent_speed
                         * self._destination_speed_multiplier)
                target_velocity = delta * (speed / distance)
                target_walk = self._destination_speed_multiplier

        # Walk strength snaps upwards, but eases back to zero at 20 units/s.
        if target_walk <= 0.0:
            self._walk_strength = move_towards(
                self._walk_strength, 0.0, dt * 20.0)
        else:
            self._walk_strength = target_walk

        velocity = self._do_velocity_update(target_velocity, dt)
        pos = pos + velocity * dt
        pos = self._clamp_to_play_area(pos)
        self.node.setPos(pos)

        if self.speed > 0.1:
            difference = abs(delta_angle(self.body_yaw, self.vel_yaw))
            smoothing = self.rotation_smooth_time * (
                2.0 if difference < 60.0 else 1.0)
            self.body_yaw, self._body_yaw_vel = smooth_damp_angle(
                self.body_yaw, self.vel_yaw, self._body_yaw_vel,
                smoothing, dt)
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
        new_speed = move_towards(current_speed, target_speed, rate)

        if target_speed > 1e-6:
            target_yaw = yaw_from_dir(target_velocity.x, target_velocity.y)
        else:
            target_yaw = self.vel_yaw

        self.vel_yaw = move_towards_angle(
            self.vel_yaw, target_yaw,
            self.rotate_speed * max(0.0, self.movement_speed_multiplier) * dt)

        velocity = dir_from_yaw(self.vel_yaw) * new_speed
        self.local_velocity = velocity
        self.speed = new_speed
        return velocity

    # ------------------------------------------------------------------ dash
    def _dash_direction_vector(self) -> Optional[Vec3]:
        if self.dash_direction == DashDirection.AllTowardsCursor:
            hit = self._cursor_ground_point()
            if hit is not None:
                delta = hit - self.agent_position
                delta.z = 0.0
                if delta.lengthSquared() > 1e-6:
                    return delta.normalized()

        if (self._is_direction and self._movement_vector is not None
                and self._movement_vector.lengthSquared() > 1e-6):
            return self._movement_vector.normalized()

        if self._destination is not None:
            delta = self._destination - self.agent_position
            delta.z = 0.0
            if delta.lengthSquared() > 1e-6:
                return delta.normalized()

        if self.dash_direction == DashDirection.CurrentMovementOnlyDodge:
            return None

        return dir_from_yaw(self.body_yaw)

    def _try_dash(self) -> None:
        if self.is_displacing or self._dash_cooldown > 0.0:
            return
        direction = self._dash_direction_vector()
        if direction is None:
            return

        dash = Dash(
            distance=self.dash_distance,
            duration=self.dash_duration,
            ease=self.dash_ease,
            rotate_forward=True,
            affected_by_movement_speed=False,
            use_linear_sweep=True,
            can_go_over_terrain=False,
        )
        dash.apply_by_direction(self, direction, on_finish=self._on_dash_finish)
        self._dash_cooldown = self.dash_cooldown

    def _on_dash_finish(self) -> None:
        self.speed = 0.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)

    # ------------------------------------------------------------------ displacement
    def start_displacement(self, displacement: Displacement) -> None:
        if displacement is None or not displacement.is_alive:
            return
        # Enemy-applied movement is refused by crowd-control immunity.
        if not displacement.is_friendly and self.has_crowd_control_immunity:
            displacement.cancel()
            return
        if self.displacement is not None:
            previous = self.displacement
            self.displacement = None
            previous.cancel()

        displacement.start()
        self.displacement = displacement
        self._disp_start = self.agent_position
        self.speed = 0.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)
        self._walk_strength = 0.0

    def cancel_displacement(self) -> None:
        displacement = self.displacement
        if displacement is None:
            return
        self.displacement = None
        displacement.cancel()

    def _finish_displacement(self) -> None:
        displacement = self.displacement
        if displacement is None:
            return
        self.displacement = None
        displacement.finish()
        self.speed = 0.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)

    def _do_displacement(self, dt: float, pos: Vec3) -> None:
        displacement = self.displacement
        if displacement is None:
            return

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
            t = displacement.elapsed_time / duration
            target = displacement.position_at(
                self._disp_start, t, multiplier)
            target = self._clamp_to_play_area(target)
            delta = target - pos

            if displacement.rotate_forward:
                self._set_body_yaw_from_direction(
                    delta, displacement.rotate_smoothly, dt)

            self.node.setPos(target)
            if displacement.elapsed_time >= duration:
                self._finish_displacement()

        elif isinstance(displacement, DispByTarget):
            target = displacement.step(pos, dt, multiplier)
            target = self._clamp_to_play_area(target)
            delta = target - pos

            if displacement.rotate_forward:
                self._set_body_yaw_from_direction(
                    delta, displacement.rotate_smoothly, dt)

            self.node.setPos(target)

            reached = False
            target_entity = displacement.target
            if target_entity is not None:
                target_pos = getattr(target_entity, "agent_position", None)
                if target_pos is not None:
                    remaining = target_pos - target
                    remaining.z = 0.0
                    reached = remaining.length() <= displacement.goal_distance + 1e-3

            if (reached or (displacement.cancel_time > 0.0
                            and displacement.elapsed_time >= displacement.cancel_time)):
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
                        duration: float = 0.25, ignore_tenacity: bool = False,
                        on_finish=None) -> DispByDestination:
        heading = Vec3(direction)
        heading.z = 0.0
        if heading.lengthSquared() < 1e-8:
            heading = dir_from_yaw(self.body_yaw)
        heading.normalize()

        start = self.agent_position
        target = start + heading * max(0.0, distance)
        destination = self.project_destination(start, target, True, False)

        displacement = DispByDestination(
            duration=max(1e-5, duration),
            ease=DewEase.EaseOutQuad,
            destination=destination,
            is_friendly=False,
            is_dodging=False,
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
        now = time.monotonic()
        self._process_input(now, camera_yaw)

        pos = self.agent_position
        if self.is_displacing:
            self._do_displacement(dt, pos)
        else:
            self._do_movement_processor_frame_update(dt, pos)

        self.node.setPos(self._clamp_to_play_area(self.agent_position))
