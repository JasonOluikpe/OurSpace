from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from panda3d.core import Vec3


class DewEase(IntEnum):
    Linear = 0
    EaseOutQuad = 1

@dataclass
class Displacement:
    duration: float = 0.25
    is_friendly: bool = False
    is_canceled_by_cc: bool = True
    rotate_forward: bool = False
    on_cancel: Optional[Callable[[], None]] = None
    on_finish: Optional[Callable[[], None]] = None

    is_alive: bool = field(default=True, init=False)
    elapsed_time: float = field(default=0.0, init=False)

    def start(self) -> None:
        self.is_alive = True
        self.elapsed_time = 0.0

    def cancel(self) -> None:
        if not self.is_alive: return
        self.is_alive = False
        if self.on_cancel: self.on_cancel()

    def finish(self) -> None:
        if not self.is_alive: return
        self.is_alive = False
        if self.on_finish: self.on_finish()

@dataclass
class DispByDestination(Displacement):
    destination: Vec3 = field(default_factory=Vec3)
    ease: DewEase = DewEase.Linear

    def position_at(self, start: Vec3, t: float) -> Vec3:
        t = max(0.0, min(1.0, t))
        if self.ease == DewEase.EaseOutQuad:
            t = 1.0 - (1.0 - t)**2
        return start + (self.destination - start) * t

@dataclass
class Dash:
    distance: float = 2.25
    duration: float = 0.25
    ease: DewEase = DewEase.Linear
    rotate_forward: bool = True

    def apply_by_direction(self, control, direction: Vec3) -> DispByDestination:
        start = control.agent_position
        heading = Vec3(direction)
        heading.z = 0.0
        if heading.lengthSquared() < 1e-8:
            heading = Vec3(0.0, 1.0, 0.0)
        heading.normalize()

        target = start + heading * self.distance
        destination = control.project_destination(start, target, True, False)

        disp = DispByDestination(
            duration=self.duration,
            ease=self.ease,
            destination=destination,
            is_friendly=True,
            is_canceled_by_cc=True,
            rotate_forward=self.rotate_forward,
        )
        control.start_displacement(disp)
        return disp
