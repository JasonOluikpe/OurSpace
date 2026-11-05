from __future__ import annotations

import math
import random
from dataclasses import dataclass

from src import layout
from src.hud import WaveBanner


@dataclass(frozen=True)
class WaveSpec:
    number: int
    minions: int = 0
    spawn_interval: float = 0.6
    implemented: bool = True


# only wave 1 is implemented; 2-5 are placeholders
WAVES = (
    WaveSpec(1, minions=20, spawn_interval=0.6),
    WaveSpec(2, implemented=False),
    WaveSpec(3, implemented=False),
    WaveSpec(4, implemented=False),
    WaveSpec(5, implemented=False)
)

START_DELAY = 3.0
COUNTDOWN = 20.0

INTRO, ACTIVE, COUNTING, IDLE, FINISHED = "intro", "active", "counting", "idle", "finished"


class WaveManager:
    def __init__(self, app, world, player, swarm) -> None:
        self.swarm = swarm
        self.banner = WaveBanner(app)

        self.index = 0
        self.state = INTRO
        self._timer = START_DELAY
        self._to_spawn = 0
        self._spawn_timer = 0.0
        self.countdown_left = 0.0

        self.banner.announce(f"Wave {self.spec.number}")

    @property
    def spec(self) -> WaveSpec:
        return WAVES[self.index]

    def _begin_wave(self) -> None:
        if not self.spec.implemented:
            self.state = IDLE
            return
        self.state = ACTIVE
        self._to_spawn = self.spec.minions
        self._spawn_timer = 0.0

    def _spawn_one(self) -> None:
        cx, cy = layout.front_door_center()
        x = cx + random.uniform(-1.6, 1.6)
        y = cy - random.uniform(2.0, 5.5)
        self.swarm.spawn(x, y)

    def _end_wave(self) -> None:
        if self.index + 1 >= len(WAVES):
            self.state = FINISHED
            return
        self.state = COUNTING
        self.countdown_left = COUNTDOWN
        self.banner.hide_announcement()

    def update(self, dt: float) -> None:
        self.banner.update(dt)

        if self.state == INTRO:
            self._timer -= dt
            if self._timer <= 0.0:
                self._begin_wave()

        elif self.state == ACTIVE:
            if self._to_spawn > 0:
                self._spawn_timer -= dt
                if self._spawn_timer <= 0.0:
                    self._spawn_one()
                    self._to_spawn -= 1
                    self._spawn_timer = self.spec.spawn_interval
            elif self.swarm.alive_count() == 0:
                self._end_wave()

        elif self.state == COUNTING:
            self.countdown_left -= dt
            if self.countdown_left <= 0.0:
                self.banner.set_countdown("")
                self.index += 1
                self.banner.announce(f"Wave {self.spec.number}")
                self._begin_wave()
            else:
                nxt = WAVES[self.index + 1].number
                self.banner.set_countdown(
                    f"Wave {nxt} starting in {math.ceil(self.countdown_left)}...")
