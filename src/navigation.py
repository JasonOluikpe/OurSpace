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

# (x, y, obstacle-or-None)
Waypoint = tuple[float, float, object]


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

        self._static = bytearray(self.nx * self.ny)
        for j in range(self.ny):
            for i in range(self.nx):
                x, y = self.center(i, j)
                if collision.blocked(x, y, radius, dynamic=False):
                    self._static[j * self.nx + i] = 1

    # ------------------------------------------------------------------ #
    def center(self, i: int, j: int) -> tuple[float, float]:
        return (self.x0 + (i + 0.5) * self.cell, self.y0 + (j + 0.5) * self.cell)

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        i = min(max(int((x - self.x0) / self.cell), 0), self.nx - 1)
        j = min(max(int((y - self.y0) / self.cell), 0), self.ny - 1)
        return i, j

    def _stamp(self):
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
                        continue # already solid (wall)
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

    def find_path(self, start: tuple[float, float], target: tuple[float, float], reach: float = 1.3) -> Optional[list[Waypoint]]:
        grid, owner = self._stamp()
        nx, ny = self.nx, self.ny
        tx, ty = target

        def goal(i: int, j: int) -> bool:
            x, y = self.center(i, j)
            if math.hypot(x - tx, y - ty) > reach:
                return False
            sx, sy = self.collision.sweep(x, y, tx, ty, 0.12, step=0.08)
            return math.hypot(sx - tx, sy - ty) < 0.1

        si, sj = self.cell_of(*start)
        if grid[sj * nx + si]:
            found = self._nearest_free(grid, si, sj)
            if found is None:
                return None
            si, sj = found

        def h(i: int, j: int) -> float:
            x, y = self.center(i, j)
            return math.hypot(x - tx, y - ty)

        open_heap = [(h(si, sj), 0.0, si, sj)]
        best = {(si, sj): 0.0}
        parent: dict[tuple[int, int], tuple[int, int]] = {}
        closed = set()

        while open_heap:
            _, g, i, j = heapq.heappop(open_heap)
            if (i, j) in closed:
                continue
            closed.add((i, j))

            if goal(i, j):
                cells = [(i, j)]
                while cells[-1] in parent:
                    cells.append(parent[cells[-1]])
                cells.reverse()
                return [(*self.center(a, b), owner.get(b * nx + a)) for a, b in cells[1:]]

            here_owner = owner.get(j * nx + i)
            for di, dj, cost in _NEIGHBOURS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or grid[nj * nx + ni]:
                    continue
                if di and dj and (grid[j * nx + ni] or grid[nj * nx + i]):
                    continue                      # no cutting corners
                ng = g + cost * self.cell
                there_owner = owner.get(nj * nx + ni)
                if there_owner is not None and there_owner is not here_owner:
                    ng += there_owner.break_cost  # pay once per obstacle crossed
                if ng < best.get((ni, nj), 1e18):
                    best[(ni, nj)] = ng
                    parent[(ni, nj)] = (i, j)
                    heapq.heappush(open_heap, (ng + h(ni, nj), ng, ni, nj))
        return None

    def _nearest_free(self, grid, i, j, max_ring: int = 3):
        for ring in range(1, max_ring + 1):
            for dj in range(-ring, ring + 1):
                for di in range(-ring, ring + 1):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < self.nx and 0 <= nj < self.ny and not grid[nj * self.nx + ni]:
                        return ni, nj
        return None
