from __future__ import annotations

import math

from src.debris import DebrisField, Piece


# Health runs 0 -> max_hp. A hit costs 1 and tears a plank off; below 1 it shatters (20 hits).
# Repair restores max_hp over REPAIR_SECONDS, flying one plank back at a time. Solid once health >= 1.
class Barrier:
    max_hp = 20
    REPAIR_SECONDS = 20.0
    FLY_TIME = 0.5
    name = "barrier"

    def _init_barrier(self, slot_nodes, debris: DebrisField) -> None:
        self.debris = debris
        self.slot_nodes = slot_nodes
        self.slot_count = len(slot_nodes)
        self.health = float(self.max_hp)
        self.broken = False
        self._placed = [True] * self.slot_count
        self._chunks = [None] * self.slot_count
        self._inflight: dict[int, object] = {}
        self._shake = 0.0

    def slot_piece(self, slot: int) -> Piece:
        raise NotImplementedError

    def _on_break(self) -> None:
        pass

    def _on_rebuilt(self) -> None:
        pass

    @property
    def display_name(self) -> str:
        return self.name.replace("_", " ")

    @property
    def break_cost(self) -> float:
        return 0.5 * max(1.0, self.health)

    @property
    def damaged(self) -> bool:
        return self.health < self.max_hp

    @property
    def percent(self) -> int:
        return int(round(100.0 * self.health / self.max_hp))

    def _target_visible(self) -> int:
        if self.health <= 0.0:
            return 0
        return int(math.ceil(self.health / self.max_hp * self.slot_count - 1e-9))

    def _count(self) -> int:
        return sum(self._placed) + len(self._inflight)

    def hit(self, from_xy) -> bool:
        if self.broken:
            return False
        self.health -= 1.0
        self._shake = 0.25
        if self.health < 1.0:
            self.break_(from_xy)
            return True
        while self._count() > self._target_visible():
            placed = [i for i in range(self.slot_count) if self._placed[i]]
            if not placed:
                break
            self._tear_off(placed[-1], from_xy, 0.7)
        return False

    def _tear_off(self, slot: int, from_xy, power: float) -> None:
        piece = self.slot_piece(slot)
        self.slot_nodes[slot].hide()
        self._placed[slot] = False
        self._chunks[slot] = self.debris.shatter([piece], from_xy, power)[0]

    def break_(self, from_xy) -> None:
        if self.broken:
            return
        self.broken = True
        self.health = 0.0

        for slot, chunk in list(self._inflight.items()):
            self.debris.abort_return(chunk)
            self._chunks[slot] = chunk
        self._inflight.clear()

        slots = [i for i in range(self.slot_count) if self._placed[i]]
        pieces = [self.slot_piece(i) for i in slots]
        for i in slots:
            self.slot_nodes[i].hide()
            self._placed[i] = False
        for i, chunk in zip(slots, self.debris.shatter(pieces, from_xy)):
            self._chunks[i] = chunk
        self._on_break()

    def repair(self, dt: float) -> bool:
        if self.health >= self.max_hp:
            return False
        self.health = min(float(self.max_hp), self.health + self.max_hp / self.REPAIR_SECONDS * dt)
        if self.broken and self.health >= 1.0:
            self.broken = False
            self._on_rebuilt()
        while self._count() < self._target_visible():
            free = [i for i in range(self.slot_count)
                    if not self._placed[i] and i not in self._inflight]
            if not free:
                break
            self._launch(free[0])
        return True

    def _launch(self, slot: int) -> None:
        chunk = self._chunks[slot]
        if chunk is None:
            self._land(slot)
            return
        self._inflight[slot] = chunk
        self.debris.fly_back(chunk, self.slot_piece(slot), self.FLY_TIME, lambda s=slot: self._land(s))

    def _land(self, slot: int) -> None:
        self._inflight.pop(slot, None)
        self._chunks[slot] = None
        self._placed[slot] = True
        self.slot_nodes[slot].show()
        self._shake = max(self._shake, 0.1)
