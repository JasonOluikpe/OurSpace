from __future__ import annotations

import math

from dataclasses import dataclass

from panda3d.core import Vec3

from src.mathutil import rotate_yaw, smooth_damp_vec3


@dataclass
class _ShakeState:
    amplitude: float
    frequency: float
    attack: float
    sustain: float
    decay: float
    seed: float
    age: float = 0.0

    @property
    def total_time(self) -> float:
        return self.attack + self.sustain + self.decay

class FollowCamera:
    def __init__(self, game, target, world) -> None:
        self.game = game
        self.camera = game.camera
        self.target = target
        self.world = world
        self.follow_smooth_time = 0.05
        self.target_height = 1.05

        self.yaw = float(-20.0)
        self.pitch = 60.0
        self.distance = 35.0

        reach = self.distance * math.cos(math.radians(self.pitch))
        height = self.distance * math.sin(math.radians(self.pitch))
        self._follow_offset = rotate_yaw(Vec3(0.0, -reach, height), self.yaw)

        self._pivot = Vec3(0.0, 0.0, 0.0)
        self._pivot_vel = Vec3(0.0, 0.0, 0.0)
        self._shakes: list[_ShakeState] = []
        self._shake_counter = 0.0

        self.shake_amplitude = 3.0
        self.shake_frequency = 1.0
        self.shake_attack_time = 0.0
        self.shake_sustain_time = 0.1
        self.shake_decay_time = 0.5
        self.shake_world_scale = 0.05
        self.shake_frequency_scale = 18.0
        self.shake_roll_scale = 10.0

        self.game.camLens.setFov(55.0)
        self.game.camLens.setNearFar(0.1, 500.0)
        self.snap()

    def do_shake(self, amplitude: float) -> None:
        self._shake_counter += 1.0
        self._shakes.append(_ShakeState(
            amplitude=amplitude * 1.25,
            frequency=self.shake_frequency * 0.9,
            attack=self.shake_attack_time * 1.25,
            sustain=self.shake_sustain_time * 1.25,
            decay=self.shake_decay_time * 1.25,
            seed=self._shake_counter * 2.399,
        ))

    def _update_shakes(self, dt: float) -> None:
        if not self._shakes: return
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
            local = shake.age
            envelope = 1.0 if shake.attack <= 0.0 else min(1.0, local / shake.attack)
            sustain_end = shake.attack + shake.sustain

            if local > sustain_end:
                envelope *= max(0.0, 1.0 - (local - sustain_end) / max(1e-6, shake.decay))

            amplitude = (shake.amplitude * self.shake_world_scale * envelope)
            frequency = max(0.01, shake.frequency * self.shake_frequency_scale)
            phase = 2.0 * math.pi * frequency * local

            offset += right * (math.sin(phase + shake.seed) * amplitude)
            offset += up * (math.sin(phase * 1.31 + shake.seed * 1.7 + 0.6) * amplitude * 0.75)
            roll += math.sin(phase * 0.77 + shake.seed * 2.3) * amplitude

        return offset, roll * self.shake_roll_scale

    def _target_point(self) -> Vec3:
        return self.target.getPos(self.game.render) + Vec3(0.0, 0.0, self.target_height)

    def snap(self) -> None:
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
            self._pivot, self._pivot_vel = smooth_damp_vec3(
                self._pivot, self._target_point(), self._pivot_vel,
                self.follow_smooth_time, dt)
            self._update_shakes(dt)
        self._apply()
