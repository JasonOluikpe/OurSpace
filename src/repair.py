from __future__ import annotations

from typing import Optional


REACH = 2.5

class RepairSystem:
    def __init__(self, app, world) -> None:
        self.world = world
        self.active = None
        self._repairing_now = False

        self.prompt = None
        aspect2d = getattr(app, "aspect2d", None)
        if aspect2d is not None:
            from direct.gui.OnscreenText import OnscreenText
            self.prompt = OnscreenText(
                text="", parent=aspect2d, pos=(0.0, -0.80), scale=0.055,
                fg=(1.0, 0.85, 0.35, 1), shadow=(0, 0, 0, 0.9), mayChange=True)

    def nearest_damaged(self, x: float, y: float):
        best, best_d = None, REACH
        for ob in self.world.obstacles:
            if not ob.damaged:
                continue
            d = ob.distance_to(x, y)
            if d < best_d:
                best, best_d = ob, d
        return best

    def hold(self, dt: float, x: float, y: float) -> Optional[object]:
        ob = self.nearest_damaged(x, y)
        self.active = ob
        if ob is not None:
            ob.repair(dt)
            self._repairing_now = True
        return ob

    def release(self) -> None:
        self.active = None

    def update(self, dt: float, x: float, y: float) -> None:
        text = ""
        if self._repairing_now and self.active is not None:
            text = f"Repairing {self.active.display_name}... {self.active.percent}%"
        else:
            ob = self.nearest_damaged(x, y)
            if ob is not None:
                text = f"Hold Triangle to repair {ob.display_name} ({ob.percent}%)"
        self._repairing_now = False
        if self.prompt is not None:
            self.prompt.setText(text)
