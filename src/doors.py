from __future__ import annotations

import math
from typing import Optional

from panda3d.core import NodePath, Point3, TransparencyAttrib

from src import layout
from src.collision import Rect
from src.barrier import Barrier
from src.debris import DebrisField, Piece
from src.layout import Box, DoorSpec
from src.meshes import make_box


COL_DOOR = (0.42, 0.30, 0.20, 1.00)
COL_GLASS = (0.55, 0.75, 0.85, 0.35)
REACH = 2.5

def _seg_rect(p, q, thick: float) -> Rect:
    if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
        return Rect(min(p[0], q[0]), p[1] - thick / 2, max(p[0], q[0]), p[1] + thick / 2)
    return Rect(p[0] - thick / 2, min(p[1], q[1]), p[0] + thick / 2, max(p[1], q[1]))


def _union_box(r1: Rect, r2: Rect, height: float) -> Box:
    return Box(min(r1.x0, r2.x0), min(r1.y0, r2.y0),
               max(r1.x1, r2.x1), max(r1.y1, r2.y1), 0.0, height)


def _smooth(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


class Door(Barrier):
    def __init__(self, spec: DoorSpec, parent: NodePath, debris: DebrisField) -> None:
        self.spec = spec
        self.name = spec.name
        self.is_open = False
        self.progress = 0.0
        self.ease = 0.0

        ax, ay = spec.a
        bx, by = spec.b
        self.length = math.hypot(bx - ax, by - ay)
        self.u = ((bx - ax) / self.length, (by - ay) / self.length)
        self.closed_rect = _seg_rect(spec.a, spec.b, layout.WALL_THICK)
        h = layout.DOOR_HEIGHT
        t = layout.DOOR_THICK
        swing = spec.kind == "swing"
        colour = COL_GLASS if spec.glass else COL_DOOR
        self._colour = colour

        self.node = parent.attachNewNode(f"door-{spec.name}")
        if swing:
            hinge = spec.b if spec.hinge_at_b else spec.a
            other = spec.a if spec.hinge_at_b else spec.b
            cd = ((other[0] - hinge[0]) / self.length, (other[1] - hinge[1]) / self.length)
            od = spec.open_normal
            self._a0 = math.degrees(math.atan2(cd[1], cd[0]))
            a1 = math.degrees(math.atan2(od[1], od[0]))
            self._delta = (a1 - self._a0 + 180.0) % 360.0 - 180.0
            self.node.setPos(hinge[0], hinge[1], 0.0)
            self.node.setH(self._a0)
            far = (hinge[0] + od[0] * self.length, hinge[1] + od[1] * self.length)
            self.open_rect = _seg_rect(hinge, far, 0.15)
            self.fade_box: Optional[Box] = _union_box(self.closed_rect, self.open_rect, h)
            self._slot_heading = None
        else:
            sdx, sdy = (self.u if spec.slide_toward_b else (-self.u[0], -self.u[1]))
            self._slide_dir = (sdx, sdy)
            self.open_rect = None
            self.fade_box = None if spec.glass else _union_box(self.closed_rect, self.closed_rect, h)
            self._slot_heading = math.degrees(math.atan2(self.u[1], self.u[0]))
            if spec.glass:
                self.node.setTransparency(TransparencyAttrib.MAlpha)
                self.node.setDepthWrite(False)

        nx = max(2, int(round(self.length / 0.6)))
        nz = 6
        pw, ph = self.length / nx, h / nz
        self._slot_dims = (pw * 0.94, ph * 0.94, t)
        self._slot_local: list[Point3] = []
        slot_nodes = []
        ox, oy = spec.slide_offset
        horizontal = abs(self.u[0]) >= abs(self.u[1])
        for k in range(nz):
            for i in range(nx):
                s0, s1 = i * pw, (i + 1) * pw
                z0, z1 = k * ph, (k + 1) * ph
                if swing:
                    box = Box(s0, -t / 2, s1, t / 2, z0, z1)
                    local = Point3((s0 + s1) / 2, 0.0, (z0 + z1) / 2)
                else:
                    p0 = (ax + self.u[0] * s0 + ox, ay + self.u[1] * s0 + oy)
                    p1 = (ax + self.u[0] * s1 + ox, ay + self.u[1] * s1 + oy)
                    if horizontal:
                        box = Box(min(p0[0], p1[0]), p0[1] - t / 2, max(p0[0], p1[0]), p0[1] + t / 2, z0, z1)
                    else:
                        box = Box(p0[0] - t / 2, min(p0[1], p1[1]), p0[0] + t / 2, max(p0[1], p1[1]), z0, z1)
                    local = Point3((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (z0 + z1) / 2)
                self._slot_local.append(local)
                slot_nodes.append(make_box("plank", box, colour, self.node))

        self._init_barrier(slot_nodes, debris)

    def slot_piece(self, slot: int) -> Piece:
        pt = self.node.getParent().getRelativePoint(self.node, self._slot_local[slot])
        heading = self.node.getH() if self.spec.kind == "swing" else self._slot_heading
        return Piece((pt.x, pt.y, pt.z), heading, self._slot_dims, self._colour)

    def _reset_pose(self) -> None:
        self.is_open = False
        self.progress = 0.0
        self.ease = 0.0
        if self.spec.kind == "swing":
            self.node.setH(self._a0)
        else:
            self.node.setPos(0.0, 0.0, 0.0)

    def _on_break(self) -> None:
        self._reset_pose()

    def _on_rebuilt(self) -> None:
        self._reset_pose()

    @property
    def center(self) -> tuple[float, float]:
        return ((self.spec.a[0] + self.spec.b[0]) / 2, (self.spec.a[1] + self.spec.b[1]) / 2)

    def distance_to(self, x: float, y: float) -> float:
        ax, ay = self.spec.a
        t = (x - ax) * self.u[0] + (y - ay) * self.u[1]
        t = max(0.0, min(self.length, t))
        return math.hypot(x - (ax + self.u[0] * t), y - (ay + self.u[1] * t))

    def _player_in_doorway(self, x: float, y: float, radius: float) -> bool:
        r = self.closed_rect
        cx, cy = min(max(x, r.x0), r.x1), min(max(y, r.y0), r.y1)
        return (x - cx) ** 2 + (y - cy) ** 2 < radius * radius

    def toggle(self, px: float, py: float, radius: float) -> bool:
        if self.broken or self.health < 1.0:
            return False
        if self.is_open and self._player_in_doorway(px, py, radius):
            return False
        self.is_open = not self.is_open
        return True

    def update(self, dt: float) -> None:
        if self.broken:
            return
        target = 1.0 if self.is_open else 0.0
        step = dt / self.spec.duration
        if self.progress < target:
            self.progress = min(target, self.progress + step)
        else:
            self.progress = max(target, self.progress - step)
        self.ease = _smooth(self.progress)

        jitter = 0.0
        if self._shake > 0.0:
            self._shake = max(0.0, self._shake - dt)
            jitter = math.sin(self._shake * 70.0) * (self._shake / 0.25)

        if self.spec.kind == "swing":
            self.node.setH(self._a0 + self._delta * self.ease + jitter * 2.5)
        else:
            s = self.ease * self.length
            nxv, nyv = -self.u[1], self.u[0]
            self.node.setPos(self._slide_dir[0] * s + nxv * jitter * 0.06,
                             self._slide_dir[1] * s + nyv * jitter * 0.06, 0.0)

    # swing doors switch to their open-leaf rect halfway; sliding doors only block the part still covered
    def collider(self) -> Optional[Rect]:
        if self.broken:
            return None
        if self.spec.kind == "swing":
            return self.closed_rect if self.ease < 0.5 else self.open_rect

        s = self.ease * self.length
        t0, t1 = (s, self.length) if self.spec.slide_toward_b else (0.0, self.length - s)
        if t1 - t0 < 0.05:
            return None
        ax, ay = self.spec.a
        p = (ax + self.u[0] * t0, ay + self.u[1] * t0)
        q = (ax + self.u[0] * t1, ay + self.u[1] * t1)
        return _seg_rect(p, q, layout.WALL_THICK)

    def nav_state(self):
        if self.broken:
            return (None, False)
        if self.is_open:
            return (self.open_rect, False) if self.spec.kind == "swing" else (None, False)
        return (self.closed_rect, True)


class DoorManager:
    def __init__(self, app, parent: NodePath, debris: DebrisField) -> None:
        self.doors = [Door(spec, parent, debris) for spec in layout.door_specs()]
        self._near: Optional[Door] = None

        self.prompt = None
        aspect2d = getattr(app, "aspect2d", None)
        if aspect2d is not None:
            from direct.gui.OnscreenText import OnscreenText
            self.prompt = OnscreenText(
                text="", parent=aspect2d, pos=(0.0, -0.88), scale=0.055,
                fg=(1, 1, 1, 1), shadow=(0, 0, 0, 0.9), mayChange=True)

    def colliders(self):
        return [d.collider for d in self.doors]

    def fade_targets(self):
        return [(d.node, d.fade_box) for d in self.doors if d.fade_box is not None]

    def nearest(self, x: float, y: float) -> Optional[Door]:
        best, best_d = None, REACH
        for d in self.doors:
            if d.broken:
                continue
            dist = d.distance_to(x, y)
            if dist < best_d:
                best, best_d = d, dist
        return best

    def toggle_nearest(self, x: float, y: float, radius: float) -> bool:
        door = self.nearest(x, y)
        return door.toggle(x, y, radius) if door is not None else False

    def update(self, dt: float, x: float, y: float) -> None:
        for d in self.doors:
            d.update(dt)
        self._near = self.nearest(x, y)
        if self.prompt is not None:
            if self._near is None:
                self.prompt.setText("")
            else:
                verb = "close" if self._near.is_open else "open"
                self.prompt.setText(f"Triangle to {verb} door")
