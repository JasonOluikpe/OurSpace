"""2D circle-vs-rectangle collision for the apartment.

The player is a circle on the XY plane; walls/furniture are axis-aligned
rectangles. `resolve` pushes a circle out of anything it overlaps (which gives
natural wall sliding), `sweep` finds how far a straight move can go (used by
dashes so they cannot tunnel through walls).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float


class CollisionWorld:
    def __init__(self, rects: Iterable[Rect], bounds: tuple[float, float, float, float]) -> None:
        self.rects = list(rects)
        self.bounds = bounds          # (xmin, ymin, xmax, ymax) for circle centers' outer limit
        self._dynamic: list[Callable[[], Optional[Rect]]] = []

    def add_dynamic(self, provider: Callable[[], Optional[Rect]]) -> None:
        """Register a collider whose rectangle can change (doors). Return None for 'no collider'."""
        self._dynamic.append(provider)

    def _all_rects(self) -> list[Rect]:
        out = list(self.rects)
        for provider in self._dynamic:
            r = provider()
            if r is not None:
                out.append(r)
        return out

    # ------------------------------------------------------------------ #
    def _push_out(self, x: float, y: float, r: float, rect: Rect) -> tuple[float, float, bool]:
        cx = min(max(x, rect.x0), rect.x1)
        cy = min(max(y, rect.y0), rect.y1)
        dx, dy = x - cx, y - cy
        d2 = dx * dx + dy * dy
        if d2 >= r * r:
            return x, y, False

        if d2 > 1e-12:
            d = math.sqrt(d2)
            push = r - d
            return x + dx / d * push, y + dy / d * push, True

        # circle center is inside the rectangle: leave through the nearest face
        faces = (
            (x - rect.x0, -1.0, 0.0, rect.x0 - r, None),
            (rect.x1 - x, 1.0, 0.0, rect.x1 + r, None),
            (y - rect.y0, 0.0, -1.0, None, rect.y0 - r),
            (rect.y1 - y, 0.0, 1.0, None, rect.y1 + r),
        )
        _, _, _, nx, ny = min(faces, key=lambda f: f[0])
        return (nx if nx is not None else x), (ny if ny is not None else y), True

    def resolve(self, x: float, y: float, radius: float) -> tuple[float, float]:
        rects = self._all_rects()
        for _ in range(4):
            moved = False
            for rect in rects:
                x, y, hit = self._push_out(x, y, radius, rect)
                moved = moved or hit
            if not moved:
                break

        xmin, ymin, xmax, ymax = self.bounds
        x = min(max(x, xmin + radius), xmax - radius)
        y = min(max(y, ymin + radius), ymax - radius)
        return x, y

    # ------------------------------------------------------------------ #
    def blocked(self, x: float, y: float, radius: float) -> bool:
        r = radius - 1e-3
        xmin, ymin, xmax, ymax = self.bounds
        if x < xmin + r or x > xmax - r or y < ymin + r or y > ymax - r:
            return True
        for rect in self._all_rects():
            cx = min(max(x, rect.x0), rect.x1)
            cy = min(max(y, rect.y0), rect.y1)
            if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                return True
        return False

    def sweep(self, sx: float, sy: float, ex: float, ey: float,
              radius: float, step: float = 0.05) -> tuple[float, float]:
        """Furthest point along start->end a circle can reach without hitting anything."""
        dist = math.hypot(ex - sx, ey - sy)
        steps = max(1, int(math.ceil(dist / step)))
        last = (sx, sy)
        for i in range(1, steps + 1):
            t = i / steps
            px, py = sx + (ex - sx) * t, sy + (ey - sy) * t
            if self.blocked(px, py, radius):
                break
            last = (px, py)
        return last