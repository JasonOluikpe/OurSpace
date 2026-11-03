"""Shape of Dreams-style camera system.

Reconstructed from ``Dew.Core.CameraManager`` / ``FxCameraShake`` with REA.

* A follow pivot chases the player with Unity's SmoothDamp
  (``followSmoothTime = 0.05``); the camera sits at a fixed offset from it.
* The angle is fixed: no rotation and no zoom.
* ``FxCameraShake`` impulse shake with its ``DoShake`` scaling, global
  multipliers and attack/sustain/decay envelope.
* The damage vignette and the big/small damage shake thresholds.

Not applicable in this single-player arena: multiplayer spectating,
occlusion raycasts, the lobby/cinematic cameras and gamepad rumble.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from panda3d.core import (
    CardMaker,
    PNMImage,
    Texture,
    TransparencyAttrib,
    Vec3,
    Vec4,
)

from .mathutil import clamp01, move_towards, rotate_yaw, smooth_damp_vec3


# ---------------------------------------------------------------------------
# Shake
# ---------------------------------------------------------------------------

class ShakeContext(IntEnum):
    """The game's five-case shake context switch.

    REA showed one case attenuating the amplitude and halving the time
    envelope; it is exposed here as ``Light``.
    """

    Default = 0
    Light = 1
    Medium = 2
    Heavy = 3
    Critical = 4


@dataclass
class _ShakeState:
    amplitude: float
    frequency: float
    attack: float
    sustain: float
    decay: float
    delay: float
    seed: float
    age: float = 0.0

    @property
    def total_time(self) -> float:
        return self.delay + self.attack + self.sustain + self.decay


# ---------------------------------------------------------------------------
# Follow camera
# ---------------------------------------------------------------------------

class FollowCamera:
    """CameraManager equivalent for this project."""

    # Static multipliers from FxCameraShake.
    Global_AmplitudeMultiplier = 1.0
    Global_FrequencyMultiplier = 1.0
    Global_TimeMultiplier = 1.0

    def __init__(
        self,
        app,
        target,
        world=None,
        *,
        yaw: float = 45.0,
        pitch: float = 60.0,
        distance: float = 26.0,
        follow_smooth_time: float = 0.05,
        target_height: float = 1.05,
        fov: float = 55.0,
    ) -> None:
        self.app = app
        self.camera = app.camera
        self.target = target
        self.world = world

        self.follow_smooth_time = follow_smooth_time
        self.target_height = target_height

        # Fixed rig: yaw is read by the player for camera-relative input.
        self.yaw = float(yaw)
        reach = distance * math.cos(math.radians(pitch))
        height = distance * math.sin(math.radians(pitch))
        self._follow_offset = rotate_yaw(Vec3(0.0, -reach, height), self.yaw)

        # --- state
        self._pivot = Vec3(0.0, 0.0, 0.0)
        self._pivot_vel = Vec3(0.0, 0.0, 0.0)
        self._shakes: list[_ShakeState] = []
        self._shake_counter = 0.0

        # --- damage overlay state
        self.min_alpha_health_threshold = 0.5
        self.max_alpha_health_threshold = 0.25
        self.max_alpha = 0.6
        self.damage_overlay_decay_speed = 0.5
        self.small_damage_threshold = 0.01
        self.small_damage_alpha = 0.2
        self.big_damage_threshold = 0.2
        self.big_damage_alpha = 1.0

        self._overlay_alpha = 0.0
        self._health_ratio = 1.0
        self._last_health: Optional[float] = None
        self._disable_overlay = False

        # --- shake tuning
        self.shake_amplitude = 3.0
        self.shake_frequency = 1.0
        self.shake_attack_time = 0.0
        self.shake_sustain_time = 0.1
        self.shake_decay_time = 0.5
        self.shake_delay = 0.0
        # Authored Cinemachine amplitudes are not world units; these scales
        # translate the recovered constants into this project.
        self.shake_world_scale = 0.05
        self.shake_frequency_scale = 18.0
        self.shake_roll_scale = 10.0
        self.is_playing_cutscene = False

        self.app.camLens.setFov(fov)
        self.app.camLens.setNearFar(0.1, 500.0)

        self._overlay = self._build_damage_overlay()
        self.snap()

    # ------------------------------------------------------------------ setup
    def _build_damage_overlay(self):
        """A stretched radial vignette drawn in render2d."""
        try:
            size = 128
            image = PNMImage(size, size, 4)
            for y in range(size):
                ny = ((y + 0.5) / size) * 2.0 - 1.0
                for x in range(size):
                    nx = ((x + 0.5) / size) * 2.0 - 1.0
                    radius = math.sqrt(nx * nx + ny * ny) / math.sqrt(2.0)
                    alpha = clamp01((radius - 0.45) / 0.55)
                    alpha = alpha * alpha * (3.0 - 2.0 * alpha)
                    image.setXel(x, y, 1.0, 1.0, 1.0)
                    image.setAlpha(x, y, alpha)

            texture = Texture("damage-vignette")
            texture.load(image)
            texture.setWrapU(Texture.WMClamp)
            texture.setWrapV(Texture.WMClamp)

            maker = CardMaker("damage-vignette")
            maker.setFrame(-1.0, 1.0, -1.0, 1.0)
            card = self.app.render2d.attachNewNode(maker.generate())
            card.setTexture(texture)
            card.setTransparency(TransparencyAttrib.MAlpha)
            card.setDepthTest(False)
            card.setDepthWrite(False)
            card.setBin("fixed", 100)
            card.setColorScale(Vec4(0.55, 0.03, 0.03, 0.0))
            return card
        except Exception:
            return None

    # ------------------------------------------------------------------ shake
    def do_shake(
        self,
        amplitude: Optional[float] = None,
        frequency: Optional[float] = None,
        attack_time: Optional[float] = None,
        sustain_time: Optional[float] = None,
        decay_time: Optional[float] = None,
        delay: Optional[float] = None,
        context: ShakeContext = ShakeContext.Default,
    ) -> None:
        """``FxCameraShake.DoShake``: apply its multipliers and enqueue."""
        if self.is_playing_cutscene:
            return

        amp = self.shake_amplitude if amplitude is None else float(amplitude)
        freq = self.shake_frequency if frequency is None else float(frequency)
        attack = self.shake_attack_time if attack_time is None else float(attack_time)
        sustain = self.shake_sustain_time if sustain_time is None else float(sustain_time)
        decay = self.shake_decay_time if decay_time is None else float(decay_time)
        wait = self.shake_delay if delay is None else float(delay)

        # Recovered DoShake scaling.
        amp *= 1.25
        freq *= 0.9
        attack *= 1.25
        sustain *= 1.25
        decay *= 1.25

        if int(context) == int(ShakeContext.Light):
            amp -= max(0.0, amp - 0.6) * 0.25
            attack *= 0.5
            sustain *= 0.5
            decay *= 0.5

        amp *= self.Global_AmplitudeMultiplier
        freq *= self.Global_FrequencyMultiplier
        attack *= self.Global_TimeMultiplier
        sustain *= self.Global_TimeMultiplier
        decay *= self.Global_TimeMultiplier

        self._shake_counter += 1.0
        self._shakes.append(_ShakeState(
            amplitude=amp,
            frequency=freq,
            attack=max(0.0, attack),
            sustain=max(0.0, sustain),
            decay=max(0.0, decay),
            delay=max(0.0, wait),
            seed=self._shake_counter * 2.399,
        ))

    def _update_shakes(self, dt: float) -> None:
        if not self._shakes:
            return
        for shake in self._shakes:
            shake.age += dt
        self._shakes = [s for s in self._shakes if s.age < s.total_time]

    def _shake_offset(self) -> tuple[Vec3, float]:
        if not self._shakes:
            return Vec3(0.0, 0.0, 0.0), 0.0

        offset = Vec3(0.0, 0.0, 0.0)
        roll = 0.0
        angle = math.radians(self.yaw)
        right = Vec3(math.cos(angle), -math.sin(angle), 0.0)
        up = Vec3(0.0, 0.0, 1.0)

        for shake in self._shakes:
            if shake.age < shake.delay:
                continue
            local = shake.age - shake.delay
            envelope = 1.0 if shake.attack <= 0.0 else min(1.0, local / shake.attack)
            sustain_end = shake.attack + shake.sustain
            if local > sustain_end:
                envelope *= max(0.0, 1.0 - (local - sustain_end)
                                / max(1e-6, shake.decay))
            amplitude = (shake.amplitude * self.shake_world_scale * envelope)
            frequency = max(0.01, shake.frequency * self.shake_frequency_scale)
            phase = 2.0 * math.pi * frequency * local
            offset += right * (math.sin(phase + shake.seed) * amplitude)
            offset += up * (math.sin(phase * 1.31 + shake.seed * 1.7 + 0.6)
                            * amplitude * 0.75)
            roll += math.sin(phase * 0.77 + shake.seed * 2.3) * amplitude

        return offset, roll * self.shake_roll_scale

    # ------------------------------------------------------------------ damage
    def on_damage(self, damage: float, max_health: float,
                  health_ratio: Optional[float] = None,
                  disable_overlay: bool = False,
                  damage_type: int = 0) -> None:
        """``ClientEntityEventOnTakeDamage`` equivalent."""
        if damage_type == 4 or max_health <= 0.0:
            return
        ratio = damage / max_health

        if not disable_overlay:
            if ratio >= self.big_damage_threshold:
                self._overlay_alpha = min(
                    1.0, self._overlay_alpha + self.big_damage_alpha)
            elif ratio >= self.small_damage_threshold:
                self._overlay_alpha = min(
                    1.0, self._overlay_alpha + self.small_damage_alpha)

        if ratio >= self.big_damage_threshold:
            self.do_shake(amplitude=3.0, context=ShakeContext.Default)
        elif ratio >= self.small_damage_threshold:
            self.do_shake(amplitude=1.2, context=ShakeContext.Light)

    def _poll_health(self) -> None:
        entity = getattr(self.app, "player", None)
        if entity is None:
            return
        health = getattr(entity, "health", None)
        max_health = getattr(entity, "max_health", None)
        if health is None or not max_health:
            return

        ratio = clamp01(health / max_health)
        if self._last_health is not None and health < self._last_health - 1e-4:
            self.on_damage(
                self._last_health - health,
                max_health,
                ratio,
                bool(getattr(entity, "disable_damage_overlay", False)),
            )
        self._last_health = health
        self._health_ratio = ratio
        self._disable_overlay = bool(
            getattr(entity, "disable_damage_overlay", False))

    def _update_damage_overlay(self, dt: float) -> None:
        if self._disable_overlay:
            minimum = 0.0
        else:
            span = (self.min_alpha_health_threshold
                    - self.max_alpha_health_threshold)
            value = 1.0 - ((self._health_ratio - self.max_alpha_health_threshold)
                           / max(1e-6, span))
            minimum = clamp01(value) * self.max_alpha

        self._overlay_alpha = move_towards(
            self._overlay_alpha, minimum,
            self.damage_overlay_decay_speed * dt)

        if self._overlay is not None:
            self._overlay.setColorScale(
                Vec4(0.55, 0.03, 0.03, self._overlay_alpha))

    # ------------------------------------------------------------------ update
    def _target_point(self) -> Vec3:
        return self.target.getPos(self.app.render) + Vec3(0.0, 0.0, self.target_height)

    def snap(self) -> None:
        """``SnapCameraToFocusedEntity``: no smoothing, immediate placement."""
        self._pivot = self._target_point()
        self._pivot_vel = Vec3(0.0, 0.0, 0.0)
        self._apply()

    def _apply(self) -> None:
        position = self._pivot + self._follow_offset
        if self.world is not None:
            position.z = max(position.z, self.world.height_at(position.x, position.y) + 1.0)

        shake, roll = self._shake_offset()
        self.camera.setPos(position + shake)
        self.camera.lookAt(self._pivot, Vec3(0.0, 0.0, 1.0))
        if roll:
            self.camera.setR(roll)

    def update(self, dt: float) -> None:
        if dt > 0.0:
            self._poll_health()
            self._pivot, self._pivot_vel = smooth_damp_vec3(
                self._pivot, self._target_point(), self._pivot_vel,
                self.follow_smooth_time, dt)
            self._update_shakes(dt)
            self._update_damage_overlay(dt)
        self._apply()
