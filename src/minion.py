from __future__ import annotations

import math
import random
from typing import Optional

from panda3d.core import Material, Vec3, Vec4

from src.mathutil import yaw_from_dir
from src.player import make_capsule


PCELL_REPLAN_DISTANCE = 3
MINION_HP = 5.0

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
        self.rank = rank
        self.alive = True
        self.flanker = False

        self.radius = 0.35
        self.speed = 3.6 * random.uniform(0.92, 1.08)
        self.stop_distance = 1.3

        self.attack_range = 1.0
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

        self.path: list = []
        self.path_cells: set[int] = set()
        self.portals: set[int] = set()
        self.reachable = True
        self.failed_key: Optional[tuple] = None
        self.plan_pcell = None
        self.plan_sig = None
        self._plan_timer = random.uniform(2.5, 3.5)
        self._since_plan = 1.0

        # set by the Swarm every frame: in a group of 3+ a minion ignores barks
        self.confident = False
        self.flee_time = 0.0
        self._flee_from = None

        self.attacking = None
        self._swing_timer = 0.0
        self._lunge = 0.0

        self.max_hp = MINION_HP
        self.hp = MINION_HP
        self._flash = 0.0

    @property
    def position(self) -> Vec3:
        return self.node.getPos()

    def needs_repath(self, pcell, sig) -> bool:
        if self.flee_time > 0.0:
            return False
        if self.failed_key is not None:
            return self.failed_key != (pcell, sig)
        if self.plan_sig is None:
            return True
        if self._since_plan < 0.3:
            return False
        if sig != self.plan_sig:
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

    @property
    def fleeing(self) -> bool:
        return self.flee_time > 0.0

    def scare(self, source, duration: float) -> None:
        if not self.alive or self.confident:
            return
        self.flee_time = max(self.flee_time, duration)
        self._flee_from = source
        self.attacking = None

    def _flee_step(self, dt: float) -> None:
        pos = self.position
        sx, sy = self._flee_from()
        ax, ay = pos.x - sx, pos.y - sy
        d = math.hypot(ax, ay) or 1.0
        base = math.atan2(ay / d, ax / d)

        col = self.world.collision
        best, best_free = None, -1.0
        for off in (0, 30, -30, 60, -60, 90, -90, 130, -130):
            a = base + math.radians(off)
            ux, uy = math.cos(a), math.sin(a)
            ex, ey = col.sweep(pos.x, pos.y, pos.x + ux * 2.5, pos.y + uy * 2.5, self.radius, step=0.1)
            free = math.hypot(ex - pos.x, ey - pos.y) - abs(off) * 0.004
            if free > best_free:
                best, best_free = (ux, uy), free
        if best is None or best_free < 0.15:
            return
        step = self.speed * 1.25 * dt
        nx, ny = col.resolve(pos.x + best[0] * step, pos.y + best[1] * step, self.radius)
        self.node.setPos(nx, ny, self.world.height_at(nx, ny))
        self.node.setH(-yaw_from_dir(best[0], best[1]))

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

    def update(self, dt: float) -> None:
        if dt <= 0.0 or not self.alive:
            return

        if self._flash > 0.0:
            self._flash -= dt
            if self._flash <= 0.0:
                self.model.clearColorScale()

        self._since_plan += dt
        self._plan_timer -= dt

        if self._lunge > 0.0:
            self._lunge = max(0.0, self._lunge - dt)
            self.model.setY(0.3 * math.sin(self._lunge / 0.2 * math.pi))
        else:
            self.model.setY(0.0)

        if self.flee_time > 0.0 and self.confident:
            self.flee_time = 0.0
            self.plan_sig = None
        if self.flee_time > 0.0:
            self.flee_time -= dt
            self.attacking = None
            self._flee_step(dt)
            if self.flee_time <= 0.0:
                self.plan_sig = None
            return

        if not self.reachable:
            self.attacking = None
            return

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

    def take_damage(self, amount: float) -> bool:
        if not self.alive:
            return False
        self.hp -= amount
        if self.hp <= 0.0:
            self.kill()
            return True
        self._flash = 0.12
        self.model.setColorScale(1.0, 0.35, 0.35, 1.0)
        return False

    def kill(self) -> None:
        if not self.alive:
            return
        self.alive = False
        self.path = []
        self.path_cells = set()
        self.node.removeNode()
