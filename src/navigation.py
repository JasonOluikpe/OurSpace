from __future__ import annotations

import heapq
import math
from typing import Optional, Sequence

from src.collision import CollisionWorld


_NEIGHBOURS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)),
)

PORTAL_MARGIN = 2.5

Waypoint = tuple[float, float, object]


# Grid A*. Static geometry is baked once; every search stamps door/fence state on top.
# Closed barriers are passable at their break_cost (a minion can smash them). "Portals" are
# the areas around each door/fence, counted so flankers can avoid the route the main group uses.
class NavGrid:
    def __init__(self, collision: CollisionWorld, radius: float,
                 obstacles: Sequence = (), cell: float = 0.5) -> None:
        self.collision = collision
        self.radius = radius
        self.cell = cell
        self.obstacles = obstacles

        xmin, ymin, xmax, ymax = collision.bounds
        self.x0, self.y0 = xmin, ymin
        self.nx = int((xmax - xmin) / cell)
        self.ny = int((ymax - ymin) / cell)

        self._cx = [xmin + (i + 0.5) * cell for i in range(self.nx)]
        self._cy = [ymin + (j + 0.5) * cell for j in range(self.ny)]
        self._coarse_w = (self.nx + 3) >> 2
        self._cache_sig = None
        self._cache = None
        self._static = bytearray(self.nx * self.ny)
        for j in range(self.ny):
            for i in range(self.nx):
                x, y = self.center(i, j)
                if collision.blocked(x, y, radius, dynamic=False):
                    self._static[j * self.nx + i] = 1

        self._portal = [0] * (self.nx * self.ny)
        for k, obs in enumerate(obstacles):
            rect = getattr(obs, "closed_rect", None) or obs.rect
            i0, j0 = self.cell_of(rect.x0 - PORTAL_MARGIN, rect.y0 - PORTAL_MARGIN)
            i1, j1 = self.cell_of(rect.x1 + PORTAL_MARGIN, rect.y1 + PORTAL_MARGIN)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    self._portal[j * self.nx + i] = k + 1

    def portals_on(self, xy_list) -> set[int]:
        out = set()
        for x, y in xy_list:
            pid = self._portal[self.index_of(x, y)]
            if pid:
                out.add(pid)
        return out

    def center(self, i: int, j: int) -> tuple[float, float]:
        return (self.x0 + (i + 0.5) * self.cell, self.y0 + (j + 0.5) * self.cell)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        i = min(max(int((x - self.x0) / self.cell), 0), self.nx - 1)
        j = min(max(int((y - self.y0) / self.cell), 0), self.ny - 1)
        return i, j

    def index_of(self, x: float, y: float) -> int:
        i, j = self.cell_of(x, y)
        return j * self.nx + i

    def coarse_key(self, x: float, y: float) -> int:
        i, j = self.cell_of(x, y)
        return (j >> 2) * self._coarse_w + (i >> 2)

    def _stamp(self):
        sig = self.state_signature()
        if sig != self._cache_sig:
            self._cache_sig = sig
            self._cache = self._build_stamp()
        return self._cache

    def _build_stamp(self):
        grid = bytearray(self._static)
        owner: dict[int, object] = {}
        r = self.radius
        for obs in self.obstacles:
            rect, breakable = obs.nav_state()
            if rect is None:
                continue
            i0, j0 = self.cell_of(rect.x0 - r, rect.y0 - r)
            i1, j1 = self.cell_of(rect.x1 + r, rect.y1 + r)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    idx = j * self.nx + i
                    if grid[idx]:
                        continue
                    x, y = self.center(i, j)
                    cx = min(max(x, rect.x0), rect.x1)
                    cy = min(max(y, rect.y0), rect.y1)
                    if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                        if breakable:
                            owner[idx] = obs
                        else:
                            grid[idx] = 1
        return grid, owner

    def state_signature(self) -> tuple:
        return tuple(obs.nav_state() for obs in self.obstacles)

    def find_path(self, start: tuple[float, float], target: tuple[float, float],
                  reach: float = 1.3, extra_cost: Optional[dict] = None,
                  extra_weight: float = 1.0, extra_cap: int = 8,
                  portal_usage: Optional[dict] = None, portal_weight: float = 0.0,
                  allow_break: bool = True) -> Optional[list[Waypoint]]:
        grid, owner = self._stamp()
        extra_cost = extra_cost or {}
        portal_usage = portal_usage or {}
        portal = self._portal
        nx, ny = self.nx, self.ny
        cx, cy = self._cx, self._cy
        tx, ty = target
        hypot = math.hypot
        sweep = self.collision.sweep

        si, sj = self.cell_of(*start)
        if grid[sj * nx + si]:
            found = self._nearest_free(grid, si, sj)
            if found is None:
                return None
            si, sj = found
        start_idx = sj * nx + si

        INF = 1e18
        best = [INF] * (nx * ny)
        parent = [-1] * (nx * ny)
        closed = bytearray(nx * ny)
        best[start_idx] = 0.0

        heap = [(hypot(cx[si] - tx, cy[sj] - ty), 0.0, start_idx)]
        push, pop = heapq.heappush, heapq.heappop
        cell = self.cell
        coarse_w = self._coarse_w
        steps = [(di, dj, di + dj * nx, cost * cell) for di, dj, cost in _NEIGHBOURS]

        while heap:
            _, g, idx = pop(heap)
            if closed[idx]:
                continue
            closed[idx] = 1
            j, i = divmod(idx, nx)

            # goal: close enough to the target with a clear line (a closed fence in between does not count)
            if hypot(cx[i] - tx, cy[j] - ty) <= reach:
                sx, sy = sweep(cx[i], cy[j], tx, ty, 0.12, step=0.08)
                if hypot(sx - tx, sy - ty) < 0.1:
                    cells = [idx]
                    while parent[cells[-1]] != -1:
                        cells.append(parent[cells[-1]])
                    cells.reverse()
                    return [(cx[c % nx], cy[c // nx], owner.get(c)) for c in cells[1:]]

            here_owner = owner.get(idx)
            for di, dj, off, step_cost in steps:
                ni, nj = i + di, j + dj
                if ni < 0 or nj < 0 or ni >= nx or nj >= ny:
                    continue
                nidx = idx + off
                if grid[nidx] or closed[nidx]:
                    continue
                if di and dj and (grid[idx + di] or grid[idx + dj * nx]):
                    continue
                ng = g + step_cost
                if extra_cost:
                    e = extra_cost.get((nj >> 2) * coarse_w + (ni >> 2), 0)
                    if e:
                        ng += extra_weight * (e if e < extra_cap else extra_cap)
                if portal_usage:
                    pid = portal[nidx]
                    if pid and pid != portal[idx]:
                        u = portal_usage.get(pid, 0)
                        if u:
                            ng += portal_weight * (u if u < 6 else 6)
                there_owner = owner.get(nidx)
                if there_owner is not None and not allow_break:
                    continue
                if there_owner is not None and there_owner is not here_owner:
                    ng += there_owner.break_cost
                if ng < best[nidx]:
                    best[nidx] = ng
                    parent[nidx] = idx
                    push(heap, (ng + hypot(cx[ni] - tx, cy[nj] - ty), ng, nidx))
        return None

    def _nearest_free(self, grid, i, j, max_ring: int = 3):
        for ring in range(1, max_ring + 1):
            for dj in range(-ring, ring + 1):
                for di in range(-ring, ring + 1):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < self.nx and 0 <= nj < self.ny and not grid[nj * self.nx + ni]:
                        return ni, nj
        return None
