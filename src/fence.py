from __future__ import annotations

import math
from typing import Optional

from src import layout
from src.barrier import Barrier
from src.collision import Rect
from src.debris import DebrisField, Piece
from src.layout import Box
from src.meshes import make_box


COL_FENCE = (0.40, 0.40, 0.40, 1.00)
MAX_CHUNK = 1.8

class Fence(Barrier):
    name = "fence"

    def __init__(self, parent, debris: DebrisField) -> None:
        c = layout.fence_collider()
        self.rect = Rect(c.x0, c.y0, c.x1, c.y1)

        specs: list[tuple[Box, Piece]] = []
        for b in layout.fence_boxes():
            w, d, th = b.x1 - b.x0, b.z1 - b.z0, b.y1 - b.y0
            n = max(1, int(math.ceil(w / MAX_CHUNK)))
            cw = w / n
            for i in range(n):
                box = Box(b.x0 + i * cw, b.y0, b.x0 + (i + 1) * cw, b.y1, b.z0, b.z1)
                centre = (box.x0 + cw / 2, (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2)
                specs.append((box, Piece(centre, 0.0, (cw * 0.97, d, th), COL_FENCE)))
        specs.sort(key=lambda sp: (round(sp[1].center[2], 3), sp[1].center[0]))

        self.node = parent.attachNewNode("fence")
        self._pieces = [p for _, p in specs]
        slot_nodes = [make_box("fence-plank", box, COL_FENCE, self.node) for box, _ in specs]
        self._init_barrier(slot_nodes, debris)

    def slot_piece(self, slot: int) -> Piece:
        return self._pieces[slot]

    def collider(self) -> Optional[Rect]:
        return None if self.broken else self.rect

    def nav_state(self):
        return (None, False) if self.broken else (self.rect, True)

    def distance_to(self, x: float, y: float) -> float:
        r = self.rect
        cx, cy = min(max(x, r.x0), r.x1), min(max(y, r.y0), r.y1)
        return math.hypot(x - cx, y - cy)

    def update(self, dt: float) -> None:
        if self._shake > 0.0:
            self._shake = max(0.0, self._shake - dt)
            amp = self._shake / 0.25
            self.node.setPos(0.0, math.sin(self._shake * 70.0) * 0.07 * amp, 0.0)
        else:
            self.node.setPos(0.0, 0.0, 0.0)
