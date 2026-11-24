"""Shared pieces for things that get smashed: oriented crush regions and destructible props."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from panda3d.core import NodePath

from src.collision import Rect


class OBB:
    """Oriented rectangle on the floor plan: origin + forward axis u, spanning s in [smin, smax] along u and
    +-half_w across it (the hand and arm of the boss are built from these)."""

    def __init__(self, ox: float, oy: float, ux: float, uy: float, smin: float, smax: float, half_w: float) -> None:
        n = math.hypot(ux, uy) or 1.0
        self.ox, self.oy = ox, oy
        self.ux, self.uy = ux / n, uy / n
        self.vx, self.vy = -self.uy, self.ux            # right-hand side normal
        self.smin, self.smax, self.hw = smin, smax, half_w

    def corners(self) -> list[tuple[float, float]]:
        out = []
        for s, t in ((self.smin, -self.hw), (self.smax, -self.hw), (self.smax, self.hw), (self.smin, self.hw)):
            out.append((self.ox + self.ux * s + self.vx * t, self.oy + self.uy * s + self.vy * t))
        return out

    def bbox(self) -> tuple[float, float, float, float]:
        c = self.corners()
        xs, ys = [p[0] for p in c], [p[1] for p in c]
        return min(xs), min(ys), max(xs), max(ys)

    def to_local(self, x: float, y: float) -> tuple[float, float]:
        dx, dy = x - self.ox, y - self.oy
        return dx * self.ux + dy * self.uy, dx * self.vx + dy * self.vy

    def distance_to_point(self, x: float, y: float) -> float:
        s, t = self.to_local(x, y)
        ds = max(self.smin - s, 0.0, s - self.smax)
        dt = max(-self.hw - t, 0.0, t - self.hw)
        return math.hypot(ds, dt)

    def hits_circle(self, x: float, y: float, r: float) -> bool:
        return self.distance_to_point(x, y) <= r

    def intersects_aabb(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        a = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        b = self.corners()
        for ax, ay in ((1.0, 0.0), (0.0, 1.0), (self.ux, self.uy), (self.vx, self.vy)):
            pa = [p[0] * ax + p[1] * ay for p in a]
            pb = [p[0] * ax + p[1] * ay for p in b]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
        return True


def hits_any(obbs, x0, y0, x1, y1) -> bool:
    return any(o.intersects_aabb(x0, y0, x1, y1) for o in obbs)


@dataclass
class Prop:
    """A piece of furniture (or curtain) that can be crushed. `rects` block walking, `area` is where it can be hit."""
    name: str
    nodes: list[NodePath]
    area: Rect
    rects: list[Rect] = field(default_factory=list)
    height: float = 1.0
    colours: list[tuple] = field(default_factory=lambda: [(0.5, 0.5, 0.5, 1.0)])
    alive: bool = True
    