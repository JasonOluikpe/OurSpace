"""Animated doors: swinging leaves and sliding panels, with live collision."""
from __future__ import annotations

import math
from typing import Optional

from panda3d.core import NodePath, TransparencyAttrib

from src import layout
from src.collision import Rect
from src.layout import Box, DoorSpec
from src.meshes import make_box

COL_DOOR = (0.42, 0.30, 0.20, 1.00)
COL_GLASS = (0.55, 0.75, 0.85, 0.35)

REACH = 2.5          # how close (m) the player must be to a door to use it


def _seg_rect(p, q, thick: float) -> Rect:
    """Axis-aligned rect around the segment p->q with the given thickness."""
    if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
        return Rect(min(p[0], q[0]), p[1] - thick / 2, max(p[0], q[0]), p[1] + thick / 2)
    return Rect(p[0] - thick / 2, min(p[1], q[1]), p[0] + thick / 2, max(p[1], q[1]))


def _union_box(r1: Rect, r2: Rect, height: float) -> Box:
    return Box(min(r1.x0, r2.x0), min(r1.y0, r2.y0),
               max(r1.x1, r2.x1), max(r1.y1, r2.y1), 0.0, height)


def _smooth(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


class Door:
    def __init__(self, spec: DoorSpec, parent: NodePath) -> None:
        self.spec = spec
        self.name = spec.name
        self.is_open = False          # target state
        self.progress = 0.0           # 0 closed .. 1 open (linear in time)
        self.ease = 0.0               # eased progress, drives visuals + collision

        ax, ay = spec.a
        bx, by = spec.b
        self.length = math.hypot(bx - ax, by - ay)
        self.u = ((bx - ax) / self.length, (by - ay) / self.length)
        self.closed_rect = _seg_rect(spec.a, spec.b, layout.WALL_THICK)
        h = layout.DOOR_HEIGHT

        if spec.kind == "swing":
            hinge = spec.b if spec.hinge_at_b else spec.a
            other = spec.a if spec.hinge_at_b else spec.b
            cd = ((other[0] - hinge[0]) / self.length, (other[1] - hinge[1]) / self.length)
            od = spec.open_normal
            self._a0 = math.degrees(math.atan2(cd[1], cd[0]))
            a1 = math.degrees(math.atan2(od[1], od[0]))
            self._delta = (a1 - self._a0 + 180.0) % 360.0 - 180.0

            self.node = parent.attachNewNode(f"door-{spec.name}")
            self.node.setPos(hinge[0], hinge[1], 0.0)
            self.node.setH(self._a0)
            leaf = Box(0.0, -layout.DOOR_THICK / 2, self.length, layout.DOOR_THICK / 2, 0.0, h)
            make_box("leaf", leaf, COL_DOOR, self.node)

            far = (hinge[0] + od[0] * self.length, hinge[1] + od[1] * self.length)
            self.open_rect = _seg_rect(hinge, far, 0.15)
            self.fade_box: Optional[Box] = _union_box(self.closed_rect, self.open_rect, h)
        else:
            sdx, sdy = (self.u if spec.slide_toward_b else (-self.u[0], -self.u[1]))
            self._slide_dir = (sdx, sdy)
            self.node = parent.attachNewNode(f"door-{spec.name}")
            ox, oy = spec.slide_offset
            pad, t = 0.10, layout.DOOR_THICK
            x0, x1 = min(ax, bx), max(ax, bx)
            y0, y1 = min(ay, by), max(ay, by)
            if abs(bx - ax) >= abs(by - ay):
                panel = Box(x0 - pad, ay + oy - t / 2, x1 + pad, ay + oy + t / 2, 0.0, h)
            else:
                panel = Box(ax + ox - t / 2, y0 - pad, ax + ox + t / 2, y1 + pad, 0.0, h)
            mesh = make_box("panel", panel, COL_GLASS if spec.glass else COL_DOOR, self.node)
            if spec.glass:
                self.node.setTransparency(TransparencyAttrib.MAlpha)
                self.node.setDepthWrite(False)
            self.open_rect = None
            self.fade_box = None if spec.glass else _union_box(self.closed_rect, self.closed_rect, h)

    # ------------------------------------------------------------------ #
    @property
    def center(self) -> tuple[float, float]:
        return ((self.spec.a[0] + self.spec.b[0]) / 2, (self.spec.a[1] + self.spec.b[1]) / 2)

    def distance_to(self, x: float, y: float) -> float:
        """Distance from a point to the doorway (segment a-b)."""
        ax, ay = self.spec.a
        t = (x - ax) * self.u[0] + (y - ay) * self.u[1]
        t = max(0.0, min(self.length, t))
        return math.hypot(x - (ax + self.u[0] * t), y - (ay + self.u[1] * t))

    def _player_in_doorway(self, x: float, y: float, radius: float) -> bool:
        r = self.closed_rect
        cx, cy = min(max(x, r.x0), r.x1), min(max(y, r.y0), r.y1)
        return (x - cx) ** 2 + (y - cy) ** 2 < radius * radius

    def toggle(self, px: float, py: float, radius: float) -> bool:
        if self.is_open and self._player_in_doorway(px, py, radius):
            return False                  # don't close it on top of the player
        self.is_open = not self.is_open
        return True

    # ------------------------------------------------------------------ #
    def update(self, dt: float) -> None:
        target = 1.0 if self.is_open else 0.0
        step = dt / self.spec.duration
        if self.progress < target:
            self.progress = min(target, self.progress + step)
        else:
            self.progress = max(target, self.progress - step)
        self.ease = _smooth(self.progress)

        if self.spec.kind == "swing":
            self.node.setH(self._a0 + self._delta * self.ease)
        else:
            s = self.ease * self.length
            self.node.setPos(self._slide_dir[0] * s, self._slide_dir[1] * s, 0.0)

    def collider(self) -> Optional[Rect]:
        if self.spec.kind == "swing":
            return self.closed_rect if self.ease < 0.5 else self.open_rect

        # sliding: only the part of the opening the panel still covers blocks
        s = self.ease * self.length
        t0, t1 = (s, self.length) if self.spec.slide_toward_b else (0.0, self.length - s)
        if t1 - t0 < 0.05:
            return None
        ax, ay = self.spec.a
        p = (ax + self.u[0] * t0, ay + self.u[1] * t0)
        q = (ax + self.u[0] * t1, ay + self.u[1] * t1)
        return _seg_rect(p, q, layout.WALL_THICK)


class DoorManager:
    def __init__(self, app, parent: NodePath) -> None:
        self.doors = [Door(spec, parent) for spec in layout.door_specs()]
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
                self.prompt.setText(f"Triangle / E: {verb} door")