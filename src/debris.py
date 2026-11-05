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


# chunks spawn standing, tumble, then settle flat on their thickness and stay there
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
        self.back = None


class DebrisField:
    def __init__(self, parent: NodePath) -> None:
        self.root = parent.attachNewNode("debris")
        self.collision = None
        self._active: list[_Chunk] = []
        self._returning: list[_Chunk] = []
        self.count = 0

    def shatter(self, pieces, from_xy: tuple[float, float], power: float = 1.0) -> list:
        fx, fy = from_xy
        chunks = []
        for piece in pieces:
            w, d, th = piece.dims
            np = make_box("debris", Box(-w / 2, -d / 2, -th / 2, w / 2, d / 2, th / 2),
                          piece.colour, self.root)
            if piece.colour[3] < 1.0:
                np.setTransparency(TransparencyAttrib.MAlpha)
                np.setDepthWrite(False)

            dx, dy = piece.center[0] - fx, piece.center[1] - fy
            dist = math.hypot(dx, dy) or 1.0
            speed = random.uniform(2.5, 6.0) * power
            vel = (dx / dist * speed + random.uniform(-1.2, 1.2),
                   dy / dist * speed + random.uniform(-1.2, 1.2),
                   random.uniform(1.0, 4.5))
            spin = (random.uniform(-420, 420), random.uniform(-420, 420), random.uniform(-420, 420))

            chunk = _Chunk(np, piece, vel, spin)
            self._place(chunk)
            self._active.append(chunk)
            chunks.append(chunk)
            self.count += 1
        return chunks

    @staticmethod
    def _place(c: _Chunk) -> None:
        c.np.setPos(c.x, c.y, c.z)
        c.np.setHpr(c.h, c.p, c.r)

    def fly_back(self, chunk: _Chunk, piece: Piece, duration: float, on_done) -> None:
        if chunk in self._active:
            self._active.remove(chunk)
        end_h, end_p, end_r = piece.heading, 90.0, 0.0
        chunk.back = {
            "t": 0.0, "dur": max(0.05, duration), "done": on_done,
            "start": (chunk.x, chunk.y, chunk.z),
            "end": piece.center,
            "hpr0": (chunk.h, chunk.p, chunk.r),
            "dhpr": (self._wrap(end_h - chunk.h), self._wrap(end_p - chunk.p), self._wrap(end_r - chunk.r)),
        }
        chunk.grounded = False
        self._returning.append(chunk)

    def abort_return(self, chunk: _Chunk) -> None:
        if chunk in self._returning:
            self._returning.remove(chunk)
        chunk.back = None
        chunk.vx = chunk.vy = 0.0
        chunk.vz = 0.5
        chunk.sh = chunk.sp = chunk.sr = 0.0
        chunk.bounces = 2
        chunk.grounded = False
        chunk.ground_time = 0.0
        chunk.done = False
        self._active.append(chunk)

    def _update_returning(self, dt: float) -> None:
        for c in list(self._returning):
            b = c.back
            b["t"] += dt
            u = min(1.0, b["t"] / b["dur"])
            e = u * u * (3.0 - 2.0 * u)
            (sx, sy, sz), (ex, ey, ez) = b["start"], b["end"]
            c.x, c.y = sx + (ex - sx) * e, sy + (ey - sy) * e
            c.z = sz + (ez - sz) * e + math.sin(math.pi * u) * 1.0
            c.h = b["hpr0"][0] + b["dhpr"][0] * e
            c.p = b["hpr0"][1] + b["dhpr"][1] * e
            c.r = b["hpr0"][2] + b["dhpr"][2] * e
            self._place(c)
            if u >= 1.0:
                self._returning.remove(c)
                c.np.removeNode()
                b["done"]()

    @staticmethod
    def _wrap(a: float) -> float:
        return (a + 180.0) % 360.0 - 180.0

    def update(self, dt: float) -> None:
        if self._returning:
            self._update_returning(dt)
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
                c.p -= c.p * k
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
