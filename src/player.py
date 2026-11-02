import math

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    Material,
    Vec3,
    Vec4,
)


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


def lerp_angle(current: float, target: float, alpha: float) -> float:
    delta = (target - current + 180.0) % 360.0 - 180.0
    return current + delta * alpha


class Player:
    """A capsule that moves on the world's height field."""

    def __init__(self, app, world) -> None:
        self.app = app
        self.world = world

        self.speed = 6.0
        self.turn_speed = 14.0
        self.gravity = 24.0
        self.jump_speed = 8.0

        self.heading = 0.0
        self._vz = 0.0
        self._airborne = False
        self._jump_queued = False
        self._keys = {"forward": False, "back": False, "left": False, "right": False}

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

        for key, action in (("w", "forward"), ("s", "back"), ("a", "left"), ("d", "right")):
            app.accept(key, self._set_key, [action, True])
            app.accept(key + "-up", self._set_key, [action, False])

        app.accept("space", self._queue_jump)

    # ------------------------------------------------------------------ input
    def _set_key(self, action: str, pressed: bool) -> None:
        self._keys[action] = pressed

    def _queue_jump(self) -> None:
        self._jump_queued = True

    # ------------------------------------------------------------------ update
    def update(self, dt: float, camera_yaw: float) -> None:
        if dt <= 0.0:
            return

        pos = self.node.getPos(self.app.render)
        x = (1.0 if self._keys["right"] else 0.0) - (1.0 if self._keys["left"] else 0.0)
        y = (1.0 if self._keys["forward"] else 0.0) - (1.0 if self._keys["back"] else 0.0)

        if x != 0.0 or y != 0.0:
            yaw = math.radians(camera_yaw)
            forward = Vec3(math.sin(yaw), math.cos(yaw), 0.0)
            right = Vec3(math.cos(yaw), -math.sin(yaw), 0.0)
            direction = forward * y + right * x
            direction.normalize()

            target_heading = math.degrees(math.atan2(direction.x, direction.y))
            alpha = 1.0 - math.exp(-self.turn_speed * dt)
            self.heading = lerp_angle(self.heading, target_heading, alpha)
            self.node.setH(self.heading)

            pos.x += direction.x * self.speed * dt
            pos.y += direction.y * self.speed * dt

        radius = math.hypot(pos.x, pos.y)
        if radius > self.world.play_radius:
            scale = self.world.play_radius / radius
            pos.x *= scale
            pos.y *= scale

        ground = self.world.height_at(pos.x, pos.y)
        if self._airborne:
            self._vz -= self.gravity * dt
            pos.z += self._vz * dt
            if pos.z <= ground:
                pos.z = ground
                self._vz = 0.0
                self._airborne = False
        else:
            pos.z = ground

        if self._jump_queued:
            if not self._airborne:
                self._vz = self.jump_speed
                self._airborne = True
            self._jump_queued = False

        self.node.setPos(pos)
