from __future__ import annotations

import math
import random
from typing import Optional

from src import layout
from src.collision import Rect
from src.debris import DebrisField, Piece
from src.meshes import make_box

COL_FENCE = (0.40, 0.40, 0.40, 1.00)
MAX_CHUNK = 1.8


class Fence:
    name = "fence"
    break_cost = 5.0 # path-length equivalent the minion pays to break it
    max_hp = 3

    def __init__(self, parent, debris: DebrisField) -> None:
        self.debris = debris
        self.hp = self.max_hp
        self.broken = False
        self._shake = 0.0

        c = layout.fence_collider()
        self.rect = Rect(c.x0, c.y0, c.x1, c.y1)
        self.parts = layout.fence_boxes()

        self.node = parent.attachNewNode("fence")
        for b in self.parts:
            make_box("fence", b, COL_FENCE, self.node)

    def collider(self) -> Optional[Rect]:
        return None if self.broken else self.rect

    def nav_state(self):
        return (None, False) if self.broken else (self.rect, True)

    def hit(self, from_xy) -> bool:
        if self.broken:
            return False
        self.hp -= 1
        self._shake = 0.25
        if self.hp <= 0:
            self.break_(from_xy)
            return True
        return False

    def update(self, dt: float) -> None:
        if self.broken:
            return
        if self._shake > 0.0:
            self._shake = max(0.0, self._shake - dt)
            amp = self._shake / 0.25
            self.node.setPos(0.0, math.sin(self._shake * 70.0) * 0.07 * amp, 0.0)
        else:
            self.node.setPos(0.0, 0.0, 0.0)

    def break_(self, from_xy) -> None:
        if self.broken:
            return
        self.broken = True
        self.node.hide()

        pieces = []
        for b in self.parts:
            w, d, th = b.x1 - b.x0, b.z1 - b.z0, b.y1 - b.y0
            cy, cz = (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2
            n = max(1, int(math.ceil(w / MAX_CHUNK)))
            cw = w / n
            for i in range(n):
                cx = b.x0 + (i + 0.5) * cw
                pieces.append(Piece((cx, cy, cz), 0.0, (cw * 0.97, d, th), COL_FENCE))
        self.debris.shatter(pieces, from_xy)
