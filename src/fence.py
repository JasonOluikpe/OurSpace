from __future__ import annotations

import math
from typing import Optional

from panda3d.core import Point3

from src import layout
from src.barrier import Barrier
from src.collision import Rect
from src.debris import DebrisField, Piece
from src.layout import Box
from src.meshes import make_box


COL_FENCE = (0.60, 0.61, 0.64, 1.00)
COL_LATCH = (0.30, 0.31, 0.35, 1.00)
COL_LATCH_LEVER = (0.80, 0.82, 0.85, 1.00)
MAX_CHUNK = 1.8
OPEN_DEGREES = -90.0        # leaf swings from along -X to along +Y: into the living room
OPEN_SECONDS = 0.6


def _smooth(p: float) -> float:
    return p * p * (3.0 - 2.0 * p)


# Baby-style gate: a fixed panel plus a swinging leaf hinged on the bedroom wall, latch on top
# of the leaf's free end. Still a Barrier, so minions can smash it and the player can repair it.
class Fence(Barrier):
    name = "gate"
    prompt_noun = "gate"

    def __init__(self, parent, debris: DebrisField) -> None:
        g = layout.gate_spec()
        self.spec = g
        h = 0.05
        self.rect = Rect(g.x0, g.y - h, g.x1, g.y + h)
        self.closed_rect = self.rect
        self.fixed_rect = Rect(g.x0, g.y - h, g.free_x, g.y + h)
        self.leaf_closed = Rect(g.free_x, g.y - h, g.x1, g.y + h)
        self.leaf_open = Rect(g.hinge_x - h, g.y, g.hinge_x + h, g.y + g.leaf_len)

        self.is_open = False
        self.progress = 0.0
        self.ease = 0.0

        self._parent = parent
        self.node = parent.attachNewNode("gate")
        self.leaf = self.node.attachNewNode("gate-leaf")
        self.leaf.setPos(g.hinge_x, g.y, 0.0)

        # (box, local-or-world centre, dims, colour, in_leaf)
        specs: list[tuple[Box, tuple, tuple, tuple, bool]] = []

        def add(b: Box, colour, in_leaf: bool, split: bool = True) -> None:
            w, d, th = b.x1 - b.x0, b.z1 - b.z0, b.y1 - b.y0
            n = max(1, int(math.ceil(w / MAX_CHUNK))) if split else 1
            cw = w / n
            for i in range(n):
                box = Box(b.x0 + i * cw, b.y0, b.x0 + (i + 1) * cw, b.y1, b.z0, b.z1)
                centre = (box.x0 + cw / 2, (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2)
                specs.append((box, centre, (cw * 0.97, d, th), colour, in_leaf))

        for b in layout.fence_boxes():
            add(b, COL_FENCE, False)
        for b in layout.gate_leaf_boxes():
            add(b, COL_FENCE, True)
        lx = -g.leaf_len + 0.10                       # latch sits on top of the free end
        fh = layout.FENCE_H
        add(Box(lx, -0.14, lx + 0.55, 0.14, fh, fh + 0.22), COL_LATCH, True, split=False)
        add(Box(lx + 0.08, -0.06, lx + 0.42, 0.06, fh + 0.22, fh + 0.34), COL_LATCH_LEVER, True, split=False)

        def world_z_x(s):
            c = s[1]
            return (round(c[2], 3), c[0] + (g.hinge_x if s[4] else 0.0))
        specs.sort(key=world_z_x)

        self._specs = specs
        slot_nodes = [make_box("gate-bar", box, colour, self.leaf if in_leaf else self.node)
                      for box, _, _, colour, in_leaf in specs]
        self._init_barrier(slot_nodes, debris)

    # ------------------------------------------------------------ barrier hooks
    def slot_piece(self, slot: int) -> Piece:
        _, centre, dims, colour, in_leaf = self._specs[slot]
        if in_leaf:
            pt = self._parent.getRelativePoint(self.leaf, Point3(*centre))
            return Piece((pt.x, pt.y, pt.z), self.leaf.getH(), dims, colour)
        return Piece(centre, 0.0, dims, colour)

    def _reset_pose(self) -> None:
        self.is_open = False
        self.progress = 0.0
        self.ease = 0.0
        self.leaf.setH(0.0)

    def _on_break(self) -> None:
        self._reset_pose()

    def _on_rebuilt(self) -> None:
        self._reset_pose()

    # ------------------------------------------------------------ colliders / nav
    def collider_fixed(self) -> Optional[Rect]:
        return None if self.broken else self.fixed_rect

    def collider_leaf(self) -> Optional[Rect]:
        if self.broken:
            return None
        return self.leaf_closed if self.ease < 0.5 else self.leaf_open

    def collider(self) -> Optional[Rect]:          # kept for callers that expect a single rect
        return None if self.broken else self.rect

    def collider_providers(self):
        return [self.collider_fixed, self.collider_leaf]

    def nav_state(self):
        if self.broken:
            return (None, False)
        if self.is_open:
            return (self.fixed_rect, True)          # the opened leaf frees a doorway
        return (self.rect, True)

    # ------------------------------------------------------------ interaction
    @staticmethod
    def _dist(x: float, y: float, r: Rect) -> float:
        cx, cy = min(max(x, r.x0), r.x1), min(max(y, r.y0), r.y1)
        return math.hypot(x - cx, y - cy)

    def distance_to(self, x: float, y: float) -> float:
        return self._dist(x, y, self.rect)

    def interact_distance(self, x: float, y: float) -> float:
        return self._dist(x, y, self.leaf_closed)

    def toggle(self, px: float, py: float, radius: float) -> bool:
        if self.broken or self.health < 1.0:
            return False
        if self.is_open and self._dist(px, py, self.leaf_closed) < radius + 0.1:
            return False                            # don't slam it on the player
        self.is_open = not self.is_open
        return True

    def update(self, dt: float) -> None:
        if not self.broken:
            target = 1.0 if self.is_open else 0.0
            step = dt / OPEN_SECONDS
            if self.progress < target:
                self.progress = min(target, self.progress + step)
            else:
                self.progress = max(target, self.progress - step)
            self.ease = _smooth(self.progress)
            self.leaf.setH(OPEN_DEGREES * self.ease)

        if self._shake > 0.0:
            self._shake = max(0.0, self._shake - dt)
            amp = self._shake / 0.25
            self.node.setPos(0.0, math.sin(self._shake * 70.0) * 0.07 * amp, 0.0)
        else:
            self.node.setPos(0.0, 0.0, 0.0)
