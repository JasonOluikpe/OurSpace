from __future__ import annotations

import math
from typing import Optional

from panda3d.core import Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter, Material, Vec3, Vec4

from src.displacement import Dash, DewEase, DispByDestination, Displacement
from src.gamepad import Gamepad
from src.mathutil import delta_angle, dir_from_yaw, move_towards, move_towards_angle, rotate_yaw, smooth_damp_angle, yaw_from_dir


def make_capsule(radius: float, height: float, segments: int = 20, cap_rings: int = 8):
    fmt = GeomVertexFormat.getV3n3()
    vdata = GeomVertexData("player-capsule", fmt, Geom.UHStatic)
    vwriter = GeomVertexWriter(vdata, "vertex")
    nwriter = GeomVertexWriter(vdata, "normal")
    prim = GeomTriangles(Geom.UHStatic)

    rows = []
    for i in range(cap_rings + 1):
        phi = -math.pi / 2.0 + (math.pi / 2.0) * i / cap_rings
        rows.append((radius + radius * math.sin(phi), radius * math.cos(phi), math.sin(phi), math.cos(phi)))
    rows.append((height - radius, radius, 0.0, 1.0))
    for i in range(1, cap_rings + 1):
        phi = (math.pi / 2.0) * i / cap_rings
        rows.append((height - radius + radius * math.sin(phi), radius * math.cos(phi), math.sin(phi), math.cos(phi)))

    next_index = 0
    ring_indices = []
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

class Player:
    def __init__(self, app, world) -> None:
        self.app = app
        self.world = world
        self.radius = 0.4

        self.base_agent_speed = 5.0
        self.normalized_acceleration = 4.0
        self.rotate_speed = 720.0
        self.rotation_smooth_time = 0.05

        self.movement_speed_multiplier = 1.0
        self.local_velocity = Vec3(0.0, 0.0, 0.0)
        self.speed = 0.0
        self.vel_yaw = 0.0
        self.body_yaw = 0.0
        self._body_yaw_vel = 0.0

        self._movement_vector: Optional[Vec3] = None

        self.dash_distance = 2.25
        self.dash_duration = 0.25
        self.dash_cooldown = 0.6
        self._dash_cooldown = 0.0

        self.displacement: Optional[Displacement] = None
        self._disp_start = Vec3(0.0, 0.0, 0.0)

        self.node = app.render.attachNewNode("player")
        self.node.setPos(world.spawn.x, world.spawn.y, world.spawn.z)

        self.model = self.node.attachNewNode(make_capsule(radius=self.radius, height=1.8))
        self.model.setTwoSided(True)

        material = Material()
        material.setDiffuse(Vec4(0.88, 0.07, 0.06, 1.0))
        material.setAmbient(Vec4(0.30, 0.02, 0.02, 1.0))
        material.setSpecular(Vec4(0.45, 0.16, 0.14, 1.0))
        material.setShininess(28.0)
        self.model.setMaterial(material, 1)

        self._interact_down = False
        self._hold_time = 0.0
        self.gamepad = Gamepad(self.app, self._try_dash, self._interact_press, self._interact_release)

    @property
    def agent_position(self) -> Vec3:
        return self.node.getPos(self.app.render)

    @property
    def current_max_agent_speed(self) -> float:
        return self.base_agent_speed * max(0.0, self.movement_speed_multiplier)

    @property
    def is_displacing(self) -> bool:
        return self.displacement is not None

    def _clamp_to_play_area(self, point: Vec3) -> Vec3:
        x, y = self.world.collision.resolve(point.x, point.y, self.radius)
        xmin, ymin, xmax, ymax = self.world.player_bounds
        point.x = min(max(x, xmin + self.radius), xmax - self.radius)
        point.y = min(max(y, ymin + self.radius), ymax - self.radius)
        point.z = self.world.height_at(point.x, point.y)
        return point

    def project_destination(self, start: Vec3, target: Vec3, use_linear_sweep: bool = True, can_go_over_terrain: bool = False) -> Vec3:
        if use_linear_sweep and not can_go_over_terrain:
            x, y = self.world.collision.sweep(start.x, start.y, target.x, target.y, self.radius)
            return self._clamp_to_play_area(Vec3(x, y, 0.0))
        return self._clamp_to_play_area(Vec3(target))

    def _process_input(self, camera_yaw: float) -> None:
        ix, iy = self.gamepad.stick()

        strength = math.hypot(ix, iy)
        if strength > 0.0:
            wish = rotate_yaw(Vec3(ix, iy, 0.0), camera_yaw) / strength
            self._movement_vector = wish * (0.4 + 0.6 * strength)
        else:
            self._movement_vector = None

    def _do_movement_processor_frame_update(self, dt: float, pos: Vec3) -> None:
        target_velocity = Vec3(0.0, 0.0, 0.0)
        if self._movement_vector is not None:
            target_velocity = self._movement_vector * self.current_max_agent_speed

        velocity = self._do_velocity_update(target_velocity, dt)
        self.node.setPos(self._clamp_to_play_area(pos + velocity * dt))

        if self.speed > 0.1:
            difference = abs(delta_angle(self.body_yaw, self.vel_yaw))
            smoothing = self.rotation_smooth_time * (2.0 if difference < 60.0 else 1.0)
            self.body_yaw, self._body_yaw_vel = smooth_damp_angle(self.body_yaw, self.vel_yaw, self._body_yaw_vel, smoothing, dt)
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

    def _try_dash(self) -> None:
        if self.is_displacing or self._dash_cooldown > 0.0:
            return

        if self._movement_vector is not None:
            direction = self._movement_vector.normalized()
        else:
            direction = dir_from_yaw(self.body_yaw)

        Dash(distance=self.dash_distance, duration=self.dash_duration, ease=DewEase.Linear).apply_by_direction(self, direction)
        self._dash_cooldown = self.dash_cooldown

    HOLD_TO_REPAIR = 0.25

    def _interact_press(self) -> None:
        if not self._interact_down:
            self._interact_down = True
            self._hold_time = 0.0

    # tap = open/close the nearest door, hold = repair the nearest damaged door/fence
    def _interact_release(self) -> None:
        if not self._interact_down:
            return
        self._interact_down = False
        self.world.repair.release()
        if self._hold_time < self.HOLD_TO_REPAIR:
            pos = self.agent_position
            self.world.doors.toggle_nearest(pos.x, pos.y, self.radius)

    def start_displacement(self, displacement: Displacement) -> None:
        if displacement is None or not displacement.is_alive: return
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
        if displacement is not None:
            displacement.finish()

    def _do_displacement(self, displacement: Displacement, dt: float, pos: Vec3) -> None:
        displacement.elapsed_time += dt

        if isinstance(displacement, DispByDestination):
            duration = max(1e-5, displacement.duration)
            target = displacement.position_at(self._disp_start, displacement.elapsed_time / duration)
            finished = displacement.elapsed_time >= duration
        else:
            self._finish_displacement()
            return

        target = self._clamp_to_play_area(target)
        if displacement.rotate_forward:
            if (target - pos).lengthSquared() > 1e-8:
                self.body_yaw = yaw_from_dir(target.x - pos.x, target.y - pos.y)
                self.node.setH(-self.body_yaw)

        self.node.setPos(target)
        if finished:
            self._finish_displacement()

    def update(self, dt: float, camera_yaw: float) -> None:
        if dt <= 0.0: return

        self._dash_cooldown = max(0.0, self._dash_cooldown - dt)
        if self._interact_down:
            self._hold_time += dt
            if self._hold_time >= self.HOLD_TO_REPAIR:
                pos = self.agent_position
                self.world.repair.hold(dt, pos.x, pos.y)
        self._process_input(camera_yaw)

        pos = self.agent_position
        if self.displacement is not None:
            self._do_displacement(self.displacement, dt, pos)
        else:
            self._do_movement_processor_frame_update(dt, pos)
