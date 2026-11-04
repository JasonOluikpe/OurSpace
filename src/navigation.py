"""Grid A* pathfinding over the collision world.

Static geometry is baked into a grid once. Door colliders change at runtime, so
they are stamped onto a copy of the grid at the start of each search: closed
doors block, open doors don't.
"""
from __future__ import annotations

import heapq
import math
from typing import Optional

from src.collision import CollisionWorld

_NEIGHBOURS = (
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)),
)


class NavGrid:
    def __init__(self, collision: CollisionWorld, radius: float, cell: float = 0.5) -> None:
        self.collision = collision
        self.radius = radius
        self.cell = cell

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

    def _with_doors(self) -> bytearray:
        grid = bytearray(self._static)
        r = self.radius
        for rect in self.collision.dynamic_rects():
            i0, j0 = self.cell_of(rect.x0 - r, rect.y0 - r)
            i1, j1 = self.cell_of(rect.x1 + r, rect.y1 + r)
            for j in range(j0, j1 + 1):
                for i in range(i0, i1 + 1):
                    x, y = self.center(i, j)
                    cx = min(max(x, rect.x0), rect.x1)
                    cy = min(max(y, rect.y0), rect.y1)
                    if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                        grid[j * self.nx + i] = 1
        return grid

    def door_signature(self) -> tuple:
        return tuple(self.collision.dynamic_rects())

    # ------------------------------------------------------------------ #
    def find_path(self, start: tuple[float, float], target: tuple[float, float],
                  reach: float = 1.3) -> Optional[list[tuple[float, float]]]:
        """Path from `start` to anywhere within `reach` of `target` that has a
        clear line to it (so a fence between them does NOT count as reachable).

        Returns waypoints (world xy), [] if already there, or None if unreachable.
        """
        grid = self._with_doors()
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
                path = [(i, j)]
                while path[-1] in parent:
                    path.append(parent[path[-1]])
                path.reverse()
                return [self.center(a, b) for a, b in path[1:]]

            for di, dj, cost in _NEIGHBOURS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < nx and 0 <= nj < ny) or grid[nj * nx + ni]:
                    continue
                if di and dj and (grid[j * nx + ni] or grid[nj * nx + i]):
                    continue                      # no cutting corners
                ng = g + cost * self.cell
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