"""Playtest minion: chases the player along A* paths, stops if unreachable."""
from __future__ import annotations

import math
from typing import Optional

from panda3d.core import Material, Vec3, Vec4

from src.mathutil import yaw_from_dir
from src.navigation import NavGrid
from src.player import make_capsule


class Minion:
    def __init__(self, app, world, player) -> None:
        self.app = app
        self.world = world
        self.player = player

        self.radius = 0.35
        self.speed = 3.6
        self.stop_distance = 1.3         # stops this close to the player (with a clear line)
        self.repath_interval = 0.25

        self.nav = NavGrid(world.collision, self.radius + 0.05)

        self.node = app.render.attachNewNode("minion")
        self.node.setPos(world.minion_spawn)
        self.model = self.node.attachNewNode(make_capsule(radius=self.radius, height=1.5))
        self.model.setTwoSided(True)
        mat = Material()
        mat.setDiffuse(Vec4(0.10, 0.70, 0.20, 1.0))
        mat.setAmbient(Vec4(0.03, 0.25, 0.06, 1.0))
        self.model.setMaterial(mat, 1)

        self.path: list[tuple[float, float]] = []
        self.reachable = True
        self._timer = 0.0
        self._failed_key: Optional[tuple] = None

    @property
    def position(self) -> Vec3:
        return self.node.getPos()

    # ------------------------------------------------------------------ #
    def _repath(self) -> None:
        pos = self.position
        target = self.player.agent_position
        pcell = self.nav.cell_of(target.x, target.y)
        key = (pcell, self.nav.door_signature())

        # already failed for exactly this situation -> stay stopped, don't re-flood the map
        if self._failed_key == key:
            return

        path = self.nav.find_path((pos.x, pos.y), (target.x, target.y), self.stop_distance)
        if path is None:
            self.reachable = False
            self.path = []
            self._failed_key = key
        else:
            self.reachable = True
            self.path = path
            self._failed_key = None

    def _next_target(self, pos: Vec3) -> Optional[tuple[float, float]]:
        """Pick the furthest upcoming waypoint we can walk to in a straight line."""
        col = self.world.collision
        # drop waypoints we are already on top of
        while self.path and math.hypot(self.path[0][0] - pos.x, self.path[0][1] - pos.y) < 0.25:
            self.path.pop(0)
        if not self.path:
            return None

        best = self.path[0]
        for k in range(min(len(self.path), 6) - 1, 0, -1):
            wx, wy = self.path[k]
            ex, ey = col.sweep(pos.x, pos.y, wx, wy, self.radius, step=0.1)
            if math.hypot(ex - wx, ey - wy) < 0.05:
                best = self.path[k]
                del self.path[:k]
                break
        return best

    # ------------------------------------------------------------------ #
    def update(self, dt: float) -> None:
        if dt <= 0.0:
            return

        self._timer -= dt
        if self._timer <= 0.0:
            self._timer = self.repath_interval
            self._repath()

        if not self.reachable:
            return                                   # can't get to the player: stand still

        pos = self.position
        target = self._next_target(pos)
        if target is None:
            # no waypoints left: close the last gap to the player if we're not there yet
            p = self.player.agent_position
            if math.hypot(p.x - pos.x, p.y - pos.y) <= self.stop_distance:
                return
            target = (p.x, p.y)

        dx, dy = target[0] - pos.x, target[1] - pos.y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return

        step = min(self.speed * dt, dist)
        nx, ny = pos.x + dx / dist * step, pos.y + dy / dist * step
        nx, ny = self.world.collision.resolve(nx, ny, self.radius)
        self.node.setPos(nx, ny, self.world.height_at(nx, ny))
        self.node.setH(-yaw_from_dir(dx, dy))