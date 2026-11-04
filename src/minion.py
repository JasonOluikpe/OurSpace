from __future__ import annotations

import math
import random
from typing import Optional

from panda3d.core import Material, Vec3, Vec4

from src.mathutil import yaw_from_dir
from src.player import make_capsule

PCELL_REPLAN_DISTANCE = 3        # replan when the player moved this many grid cells


def _dist_to_rect(x: float, y: float, rect) -> float:
    cx = min(max(x, rect.x0), rect.x1)
    cy = min(max(y, rect.y0), rect.y1)
    return math.hypot(x - cx, y - cy)


class Minion:
    def __init__(self, app, world, player, swarm, rank: int, pos: Vec3) -> None:
        self.app = app
        self.world = world
        self.player = player
        self.swarm = swarm
        self.rank = rank                  # spawn order; lower ranks plan first and "own" routes
        self.alive = True
        self.flanker = False              # set by the Swarm: flankers avoid the direct group's route

        self.radius = 0.35
        self.speed = 3.6 * random.uniform(0.92, 1.08)
        self.stop_distance = 1.3          # stops this close to the player (with a clear line)

        self.attack_range = 1.0           # distance to an obstacle at which it starts striking
        self.windup = 0.45
        self.hit_interval = 0.55

        self.node = app.render.attachNewNode(f"minion-{rank}")
        self.node.setPos(pos)
        self.model = self.node.attachNewNode(make_capsule(radius=self.radius, height=1.5))
        self.model.setTwoSided(True)
        mat = Material()
        shade = random.uniform(0.9, 1.1)
        mat.setDiffuse(Vec4(0.10 * shade, 0.70 * shade, 0.20 * shade, 1.0))
        mat.setAmbient(Vec4(0.03, 0.25, 0.06, 1.0))
        self.model.setMaterial(mat, 1)

        # planning state
        self.path: list = []              # [(x, y, obstacle|None)]
        self.path_cells: set[int] = set()
        self.portals: set[int] = set()    # doors / fence area this route passes through
        self.reachable = True
        self.failed_key: Optional[tuple] = None
        self.plan_pcell = None
        self.plan_sig = None
        self._plan_timer = random.uniform(2.5, 3.5)     # periodic refresh
        self._since_plan = 1.0

        # combat state
        self.attacking = None
        self._swing_timer = 0.0
        self._lunge = 0.0

    @property
    def position(self) -> Vec3:
        return self.node.getPos()

    # ------------------------------------------------------------------ #
    #  Planning (driven by Swarm)
    # ------------------------------------------------------------------ #
    def needs_repath(self, pcell, sig) -> bool:
        if self.failed_key is not None:                  # unreachable: wait for the situation to change
            return self.failed_key != (pcell, sig)
        if self.plan_sig is None:
            return True
        if self._since_plan < 0.3:
            return False
        if sig != self.plan_sig:                         # something broke / a door moved
            return True
        if max(abs(pcell[0] - self.plan_pcell[0]), abs(pcell[1] - self.plan_pcell[1])) > PCELL_REPLAN_DISTANCE:
            return True
        return self._plan_timer <= 0.0

    def apply_path(self, path, pcell, sig) -> None:
        self._since_plan = 0.0
        self._plan_timer = random.uniform(2.5, 3.5)
        self.plan_pcell, self.plan_sig = pcell, sig
        if path is None:
            self.reachable = False
            self.path = []
            self.path_cells = set()
            self.portals = set()
            self.failed_key = (pcell, sig)
        else:
            self.reachable = True
            self.failed_key = None
            self.path = path
            self.path_cells = {self.swarm.nav.coarse_key(x, y) for x, y, _ in path}
            self.portals = self.swarm.nav.portals_on((x, y) for x, y, _ in path)

    # ------------------------------------------------------------------ #
    def _first_obstacle(self):
        for k, (_, _, obs) in enumerate(self.path):
            if obs is not None:
                return k, obs
        return None, None

    def _next_target(self, pos: Vec3, limit: Optional[int]) -> Optional[tuple[float, float]]:
        """Furthest upcoming waypoint (before any obstacle) reachable in a straight line."""
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

    def _strike(self, obs, rect, dt: float) -> None:
        pos = self.position
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

    # ------------------------------------------------------------------ #
    def update(self, dt: float) -> None:
        if dt <= 0.0 or not self.alive:
            return

        self._since_plan += dt
        self._plan_timer -= dt

        if self._lunge > 0.0:                            # lunge animation on each strike
            self._lunge = max(0.0, self._lunge - dt)
            self.model.setY(0.3 * math.sin(self._lunge / 0.2 * math.pi))
        else:
            self.model.setY(0.0)

        if not self.reachable:
            self.attacking = None
            return                                       # can't get to the player: stand still

        pos = self.position
        k_obs, obs = self._first_obstacle()

        if obs is not None:
            rect = obs.nav_state()[0]
            if rect is not None and _dist_to_rect(pos.x, pos.y, rect) < self.attack_range:
                self._strike(obs, rect, dt)
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

    # ------------------------------------------------------------------ #
    def kill(self) -> None:
        """Hook for the (future) death system."""
        if not self.alive:
            return
        self.alive = False
        self.path = []
        self.path_cells = set()
        self.node.removeNode()