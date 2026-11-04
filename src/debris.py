from __future__ import annotations

import math
import random
from dataclasses import dataclass

from panda3d.core import NodePath, TransparencyAttrib

from src.layout import Box
from src.meshes import make_box


GRAVITY = 20.0

@dataclass(frozen=True)
class Piece:
    center: tuple[float, float, float]
    heading: float
    dims: tuple[float, float, float]
    colour: tuple[float, float, float, float]


class _Chunk:
    def __init__(self, np: NodePath, piece: Piece, vel, spin) -> None:
        self.np = np
        self.th = piece.dims[2]
        self.land_z = max(self.th / 2, min(piece.dims[0], piece.dims[1]) * 0.3)
        self.x, self.y, self.z = piece.center
        self.h, self.p, self.r = piece.heading, 90.0, 0.0
        self.vx, self.vy, self.vz = vel
        self.sh, self.sp, self.sr = spin
        self.bounces = 0
        self.grounded = False
        self.ground_time = 0.0
        self.done = False


class DebrisField:
    def __init__(self, parent: NodePath) -> None:
        self.root = parent.attachNewNode("debris")
        self.collision = None             # set by World once it exists
        self._active: list[_Chunk] = []
        self.count = 0

    def shatter(self, pieces, from_xy: tuple[float, float], power: float = 1.0) -> None:
        fx, fy = from_xy
        for piece in pieces:
            w, d, th = piece.dims
            np = make_box("debris", Box(-w / 2, -d / 2, -th / 2, w / 2, d / 2, th / 2), piece.colour, self.root)
            if piece.colour[3] < 1.0:
                np.setTransparency(TransparencyAttrib.MAlpha)
                np.setDepthWrite(False)

            dx, dy = piece.center[0] - fx, piece.center[1] - fy
            dist = math.hypot(dx, dy) or 1.0
            speed = random.uniform(2.5, 6.0) * power
            vel = (
                dx / dist * speed + random.uniform(-1.2, 1.2),
                dy / dist * speed + random.uniform(-1.2, 1.2),
                random.uniform(1.0, 4.5)
            )

            spin = (random.uniform(-420, 420), random.uniform(-420, 420), random.uniform(-420, 420))
            chunk = _Chunk(np, piece, vel, spin)
            self._place(chunk)
            self._active.append(chunk)
            self.count += 1

    @staticmethod
    def _place(c: _Chunk) -> None:
        c.np.setPos(c.x, c.y, c.z)
        c.np.setHpr(c.h, c.p, c.r)

    @staticmethod
    def _wrap(a: float) -> float:
        return (a + 180.0) % 360.0 - 180.0

    def update(self, dt: float) -> None:
        if not self._active:
            return
        still_active = []
        for c in self._active:
            if not c.grounded:
                c.vz -= GRAVITY * dt
                c.x += c.vx * dt
                c.y += c.vy * dt
                c.z += c.vz * dt
                c.h += c.sh * dt
                c.p += c.sp * dt
                c.r += c.sr * dt

                if c.z <= c.land_z:
                    c.z = c.land_z
                    if c.vz < -3.5 and c.bounces < 2:
                        c.vz = -c.vz * 0.35
                        c.vx *= 0.7
                        c.vy *= 0.7
                        c.sh *= 0.6
                        c.sp *= 0.6
                        c.sr *= 0.6
                        c.bounces += 1
                    else:
                        c.grounded = True
            else:
                c.ground_time += dt
                k = min(1.0, dt * 14.0)
                c.p = self._wrap(c.p)
                c.r = self._wrap(c.r)
                c.p -= c.p * k          # settle flat
                c.r -= c.r * k
                c.z += (c.th / 2 - c.z) * k
                damp = math.exp(-6.0 * dt)
                c.vx *= damp
                c.vy *= damp
                c.sh *= damp
                c.x += c.vx * dt
                c.y += c.vy * dt
                c.h += c.sh * dt
                if c.ground_time > 1.2:
                    c.p = c.r = 0.0
                    c.z = c.th / 2
                    c.done = True

            # keep chunks out of walls / furniture
            if self.collision is not None and (abs(c.vx) + abs(c.vy)) > 0.05:
                nx, ny = self.collision.resolve(c.x, c.y, 0.08)
                if abs(nx - c.x) + abs(ny - c.y) > 1e-6:
                    c.vx *= -0.3
                    c.vy *= -0.3
                c.x, c.y = nx, ny

            self._place(c)
            if not c.done:
                still_active.append(c)
        self._active = still_active
