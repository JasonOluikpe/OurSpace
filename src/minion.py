from __future__ import annotations

import math
from typing import Optional

from panda3d.core import Material, Vec3, Vec4

from src.mathutil import yaw_from_dir
from src.navigation import NavGrid
from src.player import make_capsule


def _dist_to_rect(x: float, y: float, rect) -> float:
    cx = min(max(x, rect.x0), rect.x1)
    cy = min(max(y, rect.y0), rect.y1)
    return math.hypot(x - cx, y - cy)


class Minion:
    def __init__(self, app, world, player) -> None:
        self.app = app
        self.world = world
        self.player = player

        self.radius = 0.35
        self.speed = 3.6
        self.stop_distance = 1.3         # stops this close to the player (with a clear line)
        self.repath_interval = 0.25

        self.attack_range = 1.0          # distance to an obstacle at which it starts striking
        self.windup = 0.45               # delay before the first strike
        self.hit_interval = 0.55         # time between strikes

        self.nav = NavGrid(world.collision, self.radius + 0.05, world.obstacles)

        self.node = app.render.attachNewNode("minion")
        self.node.setPos(world.minion_spawn)
        self.model = self.node.attachNewNode(make_capsule(radius=self.radius, height=1.5))
        self.model.setTwoSided(True)
        mat = Material()
        mat.setDiffuse(Vec4(0.10, 0.70, 0.20, 1.0))
        mat.setAmbient(Vec4(0.03, 0.25, 0.06, 1.0))
        self.model.setMaterial(mat, 1)

        self.path: list = []             # [(x, y, obstacle|None)]
        self.reachable = True
        self.attacking = None            # obstacle currently being struck
        self._swing_timer = 0.0
        self._lunge = 0.0
        self._timer = 0.0
        self._failed_key: Optional[tuple] = None

    @property
    def position(self) -> Vec3:
        return self.node.getPos()

    def _repath(self) -> None:
        pos = self.position
        target = self.player.agent_position
        pcell = self.nav.cell_of(target.x, target.y)
        key = (pcell, self.nav.state_signature())

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

    def _first_obstacle(self):
        for k, (_, _, obs) in enumerate(self.path):
            if obs is not None:
                return k, obs
        return None, None

    def _next_target(self, pos: Vec3, limit: Optional[int]) -> Optional[tuple[float, float]]:
        col = self.world.collision
        while self.path and math.hypot(self.path[0][0] - pos.x, self.path[0][1] - pos.y) < 0.25:
            self.path.pop(0)
            if limit is not None:
                limit -= 1
        if not self.path:
            return None

        best = self.path[0][:2]
        hi = min(len(self.path), 6)
        if limit is not None:
            hi = min(hi, max(limit, 1))
        for k in range(hi - 1, 0, -1):
            wx, wy = self.path[k][:2]
            ex, ey = col.sweep(pos.x, pos.y, wx, wy, self.radius, step=0.1)
            if math.hypot(ex - wx, ey - wy) < 0.05:
                best = (wx, wy)
                del self.path[:k]
                break
        return best

    # ------------------------------------------------------------------ #
    def _strike(self, obs, dt: float) -> None:
        pos = self.position
        rect = obs.nav_state()[0]
        if self.attacking is not obs:
            self.attacking = obs
            self._swing_timer = self.windup

        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        self.node.setH(-yaw_from_dir(cx - pos.x, cy - pos.y))

        self._swing_timer -= dt
        if self._swing_timer <= 0.0:
            self._swing_timer = self.hit_interval
            self._lunge = 0.2
            if obs.hit((pos.x, pos.y)):
                self.attacking = None
                self._timer = 0.0 # it's gone: find the next step now
                self._failed_key = None

    def update(self, dt: float) -> None:
        if dt <= 0.0:
            return

        # lunge animation (body lurches forward on each strike)
        if self._lunge > 0.0:
            self._lunge = max(0.0, self._lunge - dt)
            self.model.setY(0.3 * math.sin(self._lunge / 0.2 * math.pi))
        else:
            self.model.setY(0.0)

        self._timer -= dt
        if self._timer <= 0.0:
            self._timer = self.repath_interval
            self._repath()

        if not self.reachable:
            self.attacking = None
            return # can't get to the player: stand still

        pos = self.position
        k_obs, obs = self._first_obstacle()

        # the next thing in the way is breakable and we're right at it -> smash it
        if obs is not None:
            rect = obs.nav_state()[0]
            if rect is not None and _dist_to_rect(pos.x, pos.y, rect) < self.attack_range:
                self._strike(obs, dt)
                return
        self.attacking = None

        target = self._next_target(pos, k_obs)
        if target is None:
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
