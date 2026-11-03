"""Shape of Dreams-style camera system.

Reconstructed from ``Dew.Core.CameraManager`` / ``FxCameraShake`` with REA.

Implemented pieces
------------------
* A follow pivot that chases the player with Unity's SmoothDamp and
  ``followSmoothTime = 0.05``.
* A camera yaw (``entityCamAngle``).  Setting it rotates the follow offset and
  snaps the camera (``SnapCameraToFocusedEntity``).
* Zoom as a three-body blend (``farZoomBody -> midZoombody -> closeZoomBody``)
  over ``zoomSteps`` levels, smoothed with ``zoomSmoothTime = 0.2``.
* ``CameraModifierOffset`` / ``CameraModifierZoom`` local modifiers.
* ``FxCameraShake`` impulse shake with its ``DoShake`` scaling, global
  multipliers and attack/sustain/decay envelope.
* The damage vignette and the big/small damage shake thresholds.

Controls added by this module
-----------------------------
* Mouse wheel / E / Q : zoom in / out
* , / .               : rotate ``entityCamAngle`` by 22.5 degrees

Not applicable in this single-player arena: multiplayer spectating,
occlusion raycasts (there are no obstacles), the lobby/cinematic cameras and
gamepad rumble.
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


# ---------------------------------------------------------------------------
# Unity maths ports
# ---------------------------------------------------------------------------

def clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def move_towards(current: float, target: float, max_delta: float) -> float:
    if abs(target - current) <= max_delta:
        return target
    return current + math.copysign(max_delta, target - current)


def smooth_damp(current: float, target: float, velocity: float,
                smooth_time: float, dt: float) -> tuple[float, float]:
    """Port of Unity's Mathf.SmoothDamp.  Returns ``(value, new_velocity)``."""
    smooth_time = max(0.0001, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    exp = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = current - target
    temp = (velocity + omega * change) * dt
    velocity = (velocity - omega * temp) * exp
    output = target + (change + temp) * exp
    if (target - current > 0.0) == (output > target):      # no overshoot
        output = target
        velocity = (output - target) / dt if dt > 0.0 else 0.0
    return output, velocity


def smooth_damp_vec3(current: Vec3, target: Vec3, velocity: Vec3,
                     smooth_time: float, dt: float) -> tuple[Vec3, Vec3]:
    out = [0.0, 0.0, 0.0]
    vel = [0.0, 0.0, 0.0]
    cur = (current.x, current.y, current.z)
    tgt = (target.x, target.y, target.z)
    v = (velocity.x, velocity.y, velocity.z)
    for i in range(3):
        out[i], vel[i] = smooth_damp(cur[i], tgt[i], v[i], smooth_time, dt)
    return Vec3(*out), Vec3(*vel)


def rotate_yaw(vector: Vec3, yaw_degrees: float) -> Vec3:
    """Rotate a vector about +Z using this project's yaw convention.

    yaw 0 = +Y, yaw 90 = +X (matching ``entityCamAngleRotation`` usage).
    """
    angle = math.radians(yaw_degrees)
    c, s = math.cos(angle), math.sin(angle)
    return Vec3(
        vector.x * c + vector.y * s,
        -vector.x * s + vector.y * c,
        vector.z,
    )


# ---------------------------------------------------------------------------
# Camera modifiers
# ---------------------------------------------------------------------------

class CameraModifierBase:
    """``CameraModifierBase``: a temporary camera offset or zoom override."""

    def apply(self, camera: "FollowCamera"):
        if self not in camera._camera_modifiers:
            camera._camera_modifiers.append(self)
        return self

    def remove(self, camera: "FollowCamera") -> None:
        if self in camera._camera_modifiers:
            camera._camera_modifiers.remove(self)


class CameraModifierOffset(CameraModifierBase):
    """Adds a persistent world-space offset to the follow target."""

    def __init__(self, offset: Vec3) -> None:
        self.offset = Vec3(offset)


class CameraModifierZoom(CameraModifierBase):
    """Overrides the zoom level while present."""

    def __init__(self, zoom_index: float) -> None:
        self.zoom_index = float(zoom_index)


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
        zoom_steps: int = 3,
        default_zoom_level: int = 1,
        body_offsets: Optional[tuple[Vec3, Vec3, Vec3]] = None,
    ) -> None:
        self.app = app
        self.camera = app.camera
        self.target = target
        self.world = world

        # --- recovered CameraManager tuning
        self.follow_smooth_time = follow_smooth_time
        self.zoom_smooth_time = 0.2
        self.pitch = pitch
        self.distance = distance
        self.target_height = target_height
        self.zoom_steps = max(1, int(zoom_steps))
        self.default_zoom_level = max(
            0, min(self.zoom_steps - 1, int(default_zoom_level)))
        self.current_zoom_index = self.default_zoom_level

        self._entity_cam_angle = float(yaw)

        # --- state
        self._pivot = Vec3(0.0, 0.0, 0.0)
        self._pivot_vel = Vec3(0.0, 0.0, 0.0)
        self._follow_offset = Vec3(0.0, 0.0, 0.0)
        self._zoom_vel = Vec3(0.0, 0.0, 0.0)
        self._camera_modifiers: list[CameraModifierBase] = []
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
        # Authored Cinemachine amplitudes are not world units; these two
        # scales translate the recovered constants into this project.
        self.shake_world_scale = 0.05
        self.shake_frequency_scale = 18.0
        self.shake_roll_scale = 10.0
        self.is_playing_cutscene = False

        # --- zoom body offsets (the authored values are not in the DLL)
        if body_offsets is None:
            self.far_zoom_body = self._make_body(1.35)
            self.mid_zoom_body = self._make_body(1.0)
            self.close_zoom_body = self._make_body(0.72)
        else:
            self.far_zoom_body, self.mid_zoom_body, self.close_zoom_body = (
                Vec3(o) for o in body_offsets)

        self.app.camLens.setFov(fov)
        self.app.camLens.setNearFar(0.1, 500.0)

        self._overlay = self._build_damage_overlay()
        self._bind_controls()
        self.snap()

    # ------------------------------------------------------------------ setup
    def _bind_controls(self) -> None:
        self.app.accept("wheel_up", self.zoom_in)
        self.app.accept("wheel_down", self.zoom_out)
        self.app.accept("e", self.zoom_in)
        self.app.accept("q", self.zoom_out)
        self.app.accept(",", self._rotate_camera, [-22.5])
        self.app.accept(".", self._rotate_camera, [22.5])

    def _make_body(self, distance_scale: float) -> Vec3:
        d = self.distance * distance_scale
        pitch = math.radians(self.pitch)
        return Vec3(0.0, -d * math.cos(pitch), d * math.sin(pitch))

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

    # ------------------------------------------------------------------ target
    @property
    def yaw(self) -> float:
        """Alias used by main.py for camera-relative input."""
        return self._entity_cam_angle

    @yaw.setter
    def yaw(self, value: float) -> None:
        self.set_entity_cam_angle(value)

    @property
    def entity_cam_angle(self) -> float:
        return self._entity_cam_angle

    @entity_cam_angle.setter
    def entity_cam_angle(self, value: float) -> None:
        self.set_entity_cam_angle(value)

    def set_entity_cam_angle(self, angle: float, snap: bool = True) -> None:
        """Set the camera yaw; the game always snaps afterwards."""
        self._entity_cam_angle = float(angle) % 360.0
        if snap:
            self.snap()

    def rotate_by_entity_angle(self, vector: Vec3) -> Vec3:
        """``entityCamAngleRotation * vector`` equivalent."""
        return rotate_yaw(vector, self._entity_cam_angle)

    def _rotate_camera(self, step: float) -> None:
        self.set_entity_cam_angle(self._entity_cam_angle + step)

    def _target_point(self) -> Vec3:
        pos = self.target.getPos(self.app.render)
        return pos + Vec3(0.0, 0.0, self.target_height)

    def _follow_modifiers(self, target: Vec3) -> Vec3:
        result = Vec3(target)
        for modifier in self._camera_modifiers:
            if isinstance(modifier, CameraModifierOffset):
                result += modifier.offset
        return result

    # ------------------------------------------------------------------ zoom
    def _effective_zoom_index(self) -> float:
        for modifier in self._camera_modifiers:
            if isinstance(modifier, CameraModifierZoom):
                return max(0.0, min(float(self.zoom_steps - 1),
                                    modifier.zoom_index))
        return float(self.current_zoom_index)

    def _follow_offset_target(self) -> Vec3:
        steps = self.zoom_steps
        if steps <= 1:
            offset = Vec3(self.mid_zoom_body)
        else:
            t = self._effective_zoom_index() / (steps - 1)
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            if t >= 0.5:
                blend = t * 2.0 - 1.0
                offset = self.mid_zoom_body + (
                    self.close_zoom_body - self.mid_zoom_body) * blend
            else:
                blend = t * 2.0
                offset = self.far_zoom_body + (
                    self.mid_zoom_body - self.far_zoom_body) * blend
        return rotate_yaw(offset, self._entity_cam_angle)

    def set_zoom_level(self, index: int) -> None:
        self.current_zoom_index = max(
            0, min(self.zoom_steps - 1, int(index)))

    def zoom_in(self) -> None:
        self.set_zoom_level(self.current_zoom_index + 1)

    def zoom_out(self) -> None:
        self.set_zoom_level(self.current_zoom_index - 1)

    # ------------------------------------------------------------------ modifiers
    def add_local_camera_modifier(self, modifier: CameraModifierBase):
        return modifier.apply(self)

    def remove_local_camera_modifier(self, modifier: CameraModifierBase) -> None:
        modifier.remove(self)

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

    def add_shake(self, amplitude: float = 0.15, frequency: float = 22.0,
                  sustain: float = 0.1, decay: float = 0.5) -> None:
        """Compatibility helper: amplitude/frequency are in project units."""
        self.do_shake(
            amplitude=amplitude / self.shake_world_scale,
            frequency=frequency / self.shake_frequency_scale,
            sustain_time=sustain,
            decay_time=decay,
        )

    def cancel_all_shakes(self) -> None:
        self._shakes.clear()

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
        angle = math.radians(self._entity_cam_angle)
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

    @property
    def damage_overlay_alpha(self) -> float:
        return self._overlay_alpha

    # ------------------------------------------------------------------ update
    def snap(self) -> None:
        """``SnapCameraToFocusedEntity``: no smoothing, immediate placement."""
        self._pivot = self._follow_modifiers(self._target_point())
        self._pivot_vel = Vec3(0.0, 0.0, 0.0)
        self._follow_offset = self._follow_offset_target()
        self._zoom_vel = Vec3(0.0, 0.0, 0.0)
        self._apply()

    def _apply(self) -> None:
        position = self._pivot + self._follow_offset
        if self.world is not None:
            ground = self.world.height_at(position.x, position.y)
            position.z = max(position.z, ground + 1.0)

        shake, roll = self._shake_offset()
        self.camera.setPos(position + shake)
        self.camera.lookAt(self._pivot, Vec3(0.0, 0.0, 1.0))
        if roll:
            self.camera.setR(roll)

    def update(self, dt: float) -> None:
        if dt > 0.0:
            self._poll_health()

            target = self._follow_modifiers(self._target_point())
            self._pivot, self._pivot_vel = smooth_damp_vec3(
                self._pivot, target, self._pivot_vel,
                self.follow_smooth_time, dt)

            zoom_target = self._follow_offset_target()
            self._follow_offset, self._zoom_vel = smooth_damp_vec3(
                self._follow_offset, zoom_target, self._zoom_vel,
                self.zoom_smooth_time, dt)

            self._update_shakes(dt)
            self._update_damage_overlay(dt)

        self._apply()
