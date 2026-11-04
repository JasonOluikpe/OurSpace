from __future__ import annotations

import math
import random
from time import perf_counter

from panda3d.core import Vec3

from src.minion import Minion
from src.navigation import NavGrid


GROUP_SIZE = 3               # minions this close together (incl. itself) are confident
GROUP_RADIUS = 3.0
PLAN_BUDGET = 0.004          # seconds of path planning allowed per frame (at least one plan always runs)
MINION_RADIUS = 0.35
FLANK_EVERY = 3              # every 3rd minion is a flanker
FLANK_PORTAL_WEIGHT = 20.0   # metres of extra cost per direct minion already using a door / the fence
SPREAD_WEIGHT = 0.35         # how strongly the direct group spreads out

class Swarm:
    def __init__(self, app, world, player) -> None:
        self.app = app
        self.world = world
        self.player = player
        self.nav = NavGrid(world.collision, MINION_RADIUS + 0.05, world.obstacles)
        self.minions: list[Minion] = []
        self._next_rank = 0
 
    # ------------------------------------------------------------------ #
    def spawn(self, x: float, y: float) -> Minion:
        m = Minion(self.app, self.world, self.player, self, self._next_rank, Vec3(x, y, 0.0))
        m.flanker = (m.rank % FLANK_EVERY) == FLANK_EVERY - 1
        self._next_rank += 1
        self.minions.append(m)
        return m
 
    def alive(self) -> list[Minion]:
        return [m for m in self.minions if m.alive]
 
    def alive_count(self) -> int:
        return sum(1 for m in self.minions if m.alive)
 
    def kill_all(self) -> None:
        for m in self.alive():
            m.kill()
 
    # ------------------------------------------------------------------ #
    def _congestion_for(self, m: Minion):
        """-> (block_usage, portal_usage) from *earlier* minions only, which keeps every
        minion's route stable (no flip-flopping).
 
        * direct minions spread over different lanes: they avoid blocks used by everyone before them
        * flankers avoid the *portals* (fence / doors) the direct group goes through,
          so they take a different route into the living room when one exists
        """
        blocks: dict[int, int] = {}
        portals: dict[int, int] = {}
        for other in self.minions:
            if not other.alive or other.rank >= m.rank:
                continue
            if m.flanker:
                if other.flanker:
                    for key in other.path_cells:
                        blocks[key] = blocks.get(key, 0) + 1
                else:
                    for pid in other.portals:
                        portals[pid] = portals.get(pid, 0) + 1
            else:
                for key in other.path_cells:
                    blocks[key] = blocks.get(key, 0) + 1
        return blocks, portals
 
    def _plan(self, m: Minion, pcell, sig) -> None:
        pos = m.position
        target = self.player.agent_position
        blocks, portals = self._congestion_for(m)
        path = self.nav.find_path((pos.x, pos.y), (target.x, target.y), m.stop_distance,
                                  extra_cost=blocks, extra_weight=SPREAD_WEIGHT, extra_cap=8,
                                  portal_usage=portals, portal_weight=FLANK_PORTAL_WEIGHT)
        m.apply_path(path, pcell, sig)
 
    def _update_confidence(self, alive: list[Minion]) -> None:
        pts = [(m.position.x, m.position.y) for m in alive]
        r2 = GROUP_RADIUS * GROUP_RADIUS
        for i, m in enumerate(alive):
            near = 0
            for j, (x, y) in enumerate(pts):
                if (x - pts[i][0]) ** 2 + (y - pts[i][1]) ** 2 <= r2:
                    near += 1                          # includes itself
            m.confident = near >= GROUP_SIZE
 
    def update(self, dt: float) -> None:
        alive = self.alive()
        if not alive:
            return
        self._update_confidence(alive)
 
        pl = self.player.agent_position
        pcell = self.nav.cell_of(pl.x, pl.y)
        sig = self.nav.state_signature()
 
        pending = [m for m in alive if m.needs_repath(pcell, sig)]
        pending.sort(key=lambda m: (m.plan_sig is not None, -m._since_plan, m.rank))
        start = perf_counter()
        for n, m in enumerate(pending):
            if n >= 1 and perf_counter() - start > PLAN_BUDGET:
                break
            self._plan(m, pcell, sig)
 
        for m in alive:
            m.update(dt)
        self._separate(alive)
 
    def _separate(self, alive: list[Minion]) -> None:
        """Soft push so minions don't stack inside each other."""
        min_dist = MINION_RADIUS * 2.0
        moved: dict[int, tuple[float, float]] = {}
        pos = [(m.position.x, m.position.y) for m in alive]
        offs = [[0.0, 0.0] for _ in alive]
        for i in range(len(alive)):
            for j in range(i + 1, len(alive)):
                dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
                d2 = dx * dx + dy * dy
                if d2 >= min_dist * min_dist:
                    continue
                if d2 < 1e-8:
                    ang = random.uniform(0, 2 * math.pi)
                    dx, dy, d = math.cos(ang), math.sin(ang), 1.0
                else:
                    d = math.sqrt(d2)
                push = (min_dist - d) * 0.5
                ux, uy = dx / d, dy / d
                offs[i][0] += ux * push
                offs[i][1] += uy * push
                offs[j][0] -= ux * push
                offs[j][1] -= uy * push
        for m, (px, py), (ox, oy) in zip(alive, pos, offs):
            if ox or oy:
                nx, ny = self.world.collision.resolve(px + ox, py + oy, m.radius)
                m.node.setPos(nx, ny, 0.0)
 