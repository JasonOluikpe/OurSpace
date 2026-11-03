"""Displacement, dash and easing framework.

Ported from Shape of Dreams' ``Dew.Core`` (recovered with REA):

* ``Displacement``          - abstract timed movement
* ``DispByDestination``     - dash / blink towards a point
* ``DispByTarget``          - chase towards a moving target
* ``Dash``                  - builder that spawns a ``DispByDestination``
* ``DashDirection``         - how the dash direction is chosen
* ``DewEase``               - the game's 32 easing functions

The values in ``Dash`` are the ones recovered from the game:

    distance = 2.25, duration = 0.25  ->  9 units / second
    ease = Linear, rotateForward = True, useLinearSweep = True
    affectedByMovementSpeed = False
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

from panda3d.core import Vec3


# ---------------------------------------------------------------------------
# Easing (DewEase)
# ---------------------------------------------------------------------------

class DewEase(IntEnum):
    """Order taken from the game's DewEase enum."""

    Linear = 0
    EaseInQuad = 1
    EaseOutQuad = 2
    EaseInOutQuad = 3
    EaseInCubic = 4
    EaseOutCubic = 5
    EaseInOutCubic = 6
    EaseInQuart = 7
    EaseOutQuart = 8
    EaseInOutQuart = 9
    EaseInQuint = 10
    EaseOutQuint = 11
    EaseInOutQuint = 12
    EaseInSine = 13
    EaseOutSine = 14
    EaseInOutSine = 15
    EaseInExpo = 16
    EaseOutExpo = 17
    EaseInOutExpo = 18
    EaseInCirc = 19
    EaseOutCirc = 20
    EaseInOutCirc = 21
    Spring = 22
    EaseInBounce = 23
    EaseOutBounce = 24
    EaseInOutBounce = 25
    EaseInBack = 26
    EaseOutBack = 27
    EaseInOutBack = 28
    EaseInElastic = 29
    EaseOutElastic = 30
    EaseInOutElastic = 31


_C1 = 1.70158
_C3 = _C1 + 1.0
_C4 = (2.0 * math.pi) / 3.0
_C5 = (2.0 * math.pi) / 4.5


def _out_bounce(t: float) -> float:
    n1, d1 = 7.5625, 2.75
    if t < 1.0 / d1:
        return n1 * t * t
    if t < 2.0 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def _in_bounce(t: float) -> float:
    return 1.0 - _out_bounce(1.0 - t)


def _out_elastic(t: float) -> float:
    if t <= 0.0 or t >= 1.0:
        return t
    return math.pow(2.0, -10.0 * t) * math.sin((t * 10.0 - 0.75) * _C4) + 1.0


def _in_elastic(t: float) -> float:
    if t <= 0.0 or t >= 1.0:
        return t
    return -math.pow(2.0, 10.0 * t - 10.0) * math.sin((t * 10.0 - 0.75) * _C4)


def evaluate_ease(ease: DewEase | int, t: float) -> float:
    """Evaluate one of the game's easing functions at ``t`` in [0, 1]."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    try:
        ease = DewEase(ease)
    except ValueError:
        ease = DewEase.Linear

    if ease == DewEase.Linear:
        return t
    if ease == DewEase.EaseInQuad:
        return t * t
    if ease == DewEase.EaseOutQuad:
        return 1.0 - (1.0 - t) * (1.0 - t)
    if ease == DewEase.EaseInOutQuad:
        return 2.0 * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 2.0) / 2.0
    if ease == DewEase.EaseInCubic:
        return t * t * t
    if ease == DewEase.EaseOutCubic:
        return 1.0 - pow(1.0 - t, 3.0)
    if ease == DewEase.EaseInOutCubic:
        return 4.0 * t * t * t if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0
    if ease == DewEase.EaseInQuart:
        return t ** 4
    if ease == DewEase.EaseOutQuart:
        return 1.0 - pow(1.0 - t, 4.0)
    if ease == DewEase.EaseInOutQuart:
        return 8.0 * t ** 4 if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 4.0) / 2.0
    if ease == DewEase.EaseInQuint:
        return t ** 5
    if ease == DewEase.EaseOutQuint:
        return 1.0 - pow(1.0 - t, 5.0)
    if ease == DewEase.EaseInOutQuint:
        return 16.0 * t ** 5 if t < 0.5 else 1.0 - pow(-2.0 * t + 2.0, 5.0) / 2.0
    if ease == DewEase.EaseInSine:
        return 1.0 - math.cos((t * math.pi) / 2.0)
    if ease == DewEase.EaseOutSine:
        return math.sin((t * math.pi) / 2.0)
    if ease == DewEase.EaseInOutSine:
        return -(math.cos(math.pi * t) - 1.0) / 2.0
    if ease == DewEase.EaseInExpo:
        return 0.0 if t == 0.0 else pow(2.0, 10.0 * t - 10.0)
    if ease == DewEase.EaseOutExpo:
        return 1.0 if t == 1.0 else 1.0 - pow(2.0, -10.0 * t)
    if ease == DewEase.EaseInOutExpo:
        if t == 0.0 or t == 1.0:
            return t
        if t < 0.5:
            return pow(2.0, 20.0 * t - 10.0) / 2.0
        return (2.0 - pow(2.0, -20.0 * t + 10.0)) / 2.0
    if ease == DewEase.EaseInCirc:
        return 1.0 - math.sqrt(max(0.0, 1.0 - t * t))
    if ease == DewEase.EaseOutCirc:
        return math.sqrt(max(0.0, 1.0 - pow(t - 1.0, 2.0)))
    if ease == DewEase.EaseInOutCirc:
        if t < 0.5:
            return (1.0 - math.sqrt(max(0.0, 1.0 - pow(2.0 * t, 2.0)))) / 2.0
        return (math.sqrt(max(0.0, 1.0 - pow(-2.0 * t + 2.0, 2.0))) + 1.0) / 2.0
    if ease == DewEase.Spring:
        return 1.0 - math.exp(-6.0 * t) * math.cos(10.0 * t)
    if ease == DewEase.EaseInBounce:
        return _in_bounce(t)
    if ease == DewEase.EaseOutBounce:
        return _out_bounce(t)
    if ease == DewEase.EaseInOutBounce:
        if t < 0.5:
            return (1.0 - _out_bounce(1.0 - 2.0 * t)) / 2.0
        return (1.0 + _out_bounce(2.0 * t - 1.0)) / 2.0
    if ease == DewEase.EaseInBack:
        return _C3 * t * t * t - _C1 * t * t
    if ease == DewEase.EaseOutBack:
        return 1.0 + _C3 * pow(t - 1.0, 3.0) + _C1 * pow(t - 1.0, 2.0)
    if ease == DewEase.EaseInOutBack:
        if t < 0.5:
            return (pow(2.0 * t, 2.0) * ((_C1 + 1.0) * 2.0 * t - _C1)) / 2.0
        return (pow(2.0 * t - 2.0, 2.0) * ((_C1 + 1.0) * (t * 2.0 - 2.0) + _C1) + 2.0) / 2.0
    if ease == DewEase.EaseInElastic:
        return _in_elastic(t)
    if ease == DewEase.EaseOutElastic:
        return _out_elastic(t)
    if ease == DewEase.EaseInOutElastic:
        if t <= 0.0 or t >= 1.0:
            return t
        if t < 0.5:
            return -(pow(2.0, 20.0 * t - 10.0) * math.sin((20.0 * t - 11.125) * _C5)) / 2.0
        return (pow(2.0, -20.0 * t + 10.0) * math.sin((20.0 * t - 11.125) * _C5)) / 2.0 + 1.0
    return t


# ---------------------------------------------------------------------------
# Displacement
# ---------------------------------------------------------------------------

@dataclass
class Displacement:
    """Base class for timed movement (``Displacement`` in Dew.Core)."""

    duration: float = 0.25
    is_friendly: bool = False          # friendly => counts as a dash
    is_dodging: bool = False
    is_canceled_by_cc: bool = True
    affected_by_movement_speed: bool = False
    rotate_forward: bool = False
    rotate_smoothly: bool = False
    on_cancel: Optional[Callable[[], None]] = None
    on_finish: Optional[Callable[[], None]] = None
    minimum_duration: float = 0.0

    is_alive: bool = field(default=True, init=False)
    has_started: bool = field(default=False, init=False)
    elapsed_time: float = field(default=0.0, init=False)

    def start(self) -> None:
        self.is_alive = True
        self.has_started = True
        self.elapsed_time = 0.0

    def cancel(self) -> None:
        if not self.is_alive:
            return
        self.is_alive = False
        callback = self.on_cancel
        if callback is not None:
            callback()

    def finish(self) -> None:
        if not self.is_alive:
            return
        self.is_alive = False
        callback = self.on_finish
        if callback is not None:
            callback()


@dataclass
class DispByDestination(Displacement):
    """Movement to a fixed point (the dash/blink case)."""

    destination: Vec3 = field(default_factory=Vec3)
    ease: DewEase = DewEase.Linear
    curve: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    curve_horizontal_distance: Optional[float] = None
    can_go_over_terrain: bool = False

    def position_at(self, start: Vec3, t: float, speed_multiplier: float = 1.0) -> Vec3:
        """Position along the eased path at normalized time ``t``."""
        t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        end = start + (self.destination - start) * max(0.0, speed_multiplier)
        eased = evaluate_ease(self.ease, t)

        # The game evaluates a cubic Bezier when a curve is authored; the
        # default dash has no curve, so this branch is normally skipped.
        if any(self.curve):
            direction = Vec3(end.x - start.x, end.y - start.y, 0.0)
            if direction.lengthSquared() > 1e-8:
                direction.normalize()
                right = Vec3(direction.y, -direction.x, 0.0)
                p1 = start + right * self.curve[0] + direction * self.curve[1]
                p2 = end + right * self.curve[2] + direction * self.curve[3]
                om = 1.0 - eased
                pos = (start * (om ** 3) + p1 * (3.0 * om * om * eased)
                       + p2 * (3.0 * om * eased * eased) + end * (eased ** 3))
                pos.z = start.z + (end.z - start.z) * eased
                return pos

        return start + (end - start) * eased


@dataclass
class DispByTarget(Displacement):
    """Movement towards a moving target (``DispByTarget`` in Dew.Core)."""

    target: object = None
    goal_distance: float = 0.0
    speed: float = 10.0
    cancel_time: float = 0.0

    def step(self, current: Vec3, dt: float, speed_multiplier: float = 1.0) -> Vec3:
        if self.target is None:
            return current
        target_pos = getattr(self.target, "agent_position", None)
        if target_pos is None:
            target_pos = self.target.getPos(self.target.getParent())
        delta = target_pos - current
        delta.z = 0.0
        distance = delta.length()
        if distance <= self.goal_distance or distance < 1e-8:
            return current
        travel = min(max(0.0, self.speed * speed_multiplier * dt),
                     distance - self.goal_distance)
        return current + delta.normalized() * travel


# ---------------------------------------------------------------------------
# Dash builder
# ---------------------------------------------------------------------------

class DashDirection(IntEnum):
    CurrentMovement = 0
    CurrentMovementOnlyDodge = 1
    AllTowardsCursor = 2


@dataclass
class Dash:
    """Builder that turns a direction/destination into a displacement."""

    distance: float = 2.25
    duration: float = 0.25
    ease: DewEase = DewEase.Linear
    rotate_forward: bool = True
    affected_by_movement_speed: bool = False
    use_linear_sweep: bool = True
    can_go_over_terrain: bool = False

    def apply_by_direction(self, control, direction: Vec3,
                           on_finish: Optional[Callable[[], None]] = None) -> DispByDestination:
        start = control.agent_position
        heading = Vec3(direction)
        heading.z = 0.0
        if heading.lengthSquared() < 1e-8:
            heading = Vec3(0.0, 1.0, 0.0)
        heading.normalize()

        target = start + heading * self.distance
        destination = control.project_destination(
            start, target, self.use_linear_sweep, self.can_go_over_terrain)

        disp = DispByDestination(
            duration=self.duration,
            ease=self.ease,
            destination=destination,
            is_friendly=True,
            is_canceled_by_cc=True,
            affected_by_movement_speed=self.affected_by_movement_speed,
            rotate_forward=self.rotate_forward,
            can_go_over_terrain=self.can_go_over_terrain,
            on_finish=on_finish,
        )
        control.start_displacement(disp)
        return disp

    def apply_by_destination(self, control, destination: Vec3,
                             on_finish: Optional[Callable[[], None]] = None) -> DispByDestination:
        return self.apply_by_direction(
            control, Vec3(destination) - control.agent_position, on_finish)
