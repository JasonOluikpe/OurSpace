from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from panda3d.core import NodePath

from src.meshes import MeshBuilder


# Everything here lives in the city's REAL-metre frame (see city.py): +X east, +Y north.
# Bay St runs north-south east of our tower; St Joseph St runs east-west in front of it.
# Traffic only exists near the focus (the player): cars spawn at the upstream edge of a window
# around it and are removed at the downstream edge, so nothing far away is ever simulated or drawn.

WINDOW = 90.0            # half length of the active window along each lane (real m)
HIDE_DIST = 100.0
CYCLE = 28.0


@dataclass(frozen=True)
class Lane:
    axis: str            # "y": travels along Y at x = pos;  "x": travels along X at y = pos
    pos: float
    dir: int             # +1 / -1 along the axis
    group: str           # "BAY", "SJ" (signal-controlled) or "EM" (emergency lane, ignores lights)
    stop: float | None   # stop-line coordinate along the axis


LANES = [
    Lane("y", 8.0, -1, "BAY", 23.4), Lane("y", 12.5, -1, "BAY", 23.4),        # southbound (west half)
    Lane("y", 21.5, +1, "BAY", 4.6), Lane("y", 26.0, +1, "BAY", 4.6),         # northbound (east half)
    Lane("x", 11.5, +1, "SJ", 0.2), Lane("x", 16.5, -1, "SJ", 33.9),          # St Joseph: eastbound / westbound
]
EM_LANES = [Lane("y", 15.3, -1, "EM", None), Lane("y", 18.7, +1, "EM", None)]

CAR_COLOURS = [(0.92, 0.92, 0.93), (0.06, 0.06, 0.07), (0.62, 0.64, 0.68), (0.22, 0.23, 0.26),
               (0.12, 0.20, 0.38), (0.62, 0.10, 0.10), (0.35, 0.37, 0.32), (0.78, 0.70, 0.55)]
KINDS = {"sedan": 4.6, "suv": 4.9, "taxi": 4.6, "bus": 12.0, "ambulance": 6.0, "fire": 9.5, "police": 4.8}
CAR_SCALE = 0.7         # the city frame is 2x; this brings cars closer to player scale


# ------------------------------------------------------------------------------ vehicle meshes
def _wheels(mb: MeshBuilder, W: float, ys, r: float = 0.34) -> None:
    for y in ys:
        for sx in (-1, 1):
            x = sx * (W / 2 - 0.1)
            mb.cyl_between((x - 0.13, y, r), (x + 0.13, y, r), r, (0.05, 0.05, 0.06), 10)


def _lamps(lm: MeshBuilder, L: float, W: float, z: float) -> None:
    for sx in (-1, 1):
        lm.box(sx * (W / 2 - 0.40) - 0.2, L / 2 - 0.04, z, sx * (W / 2 - 0.40) + 0.2, L / 2 + 0.02, z + 0.16, (1.0, 0.95, 0.72))
        lm.box(sx * (W / 2 - 0.40) - 0.2, -L / 2 - 0.02, z, sx * (W / 2 - 0.40) + 0.2, -L / 2 + 0.04, z + 0.14, (0.95, 0.10, 0.08))


def _lightbar(lm: MeshBuilder, y: float, z: float, w: float) -> None:
    pass    # lightbar halves are separate flashing nodes, see _flash_nodes


def _build(kind: str, body, parent: NodePath) -> NodePath:
    root = parent.attachNewNode(f"veh-{kind}")
    L = KINDS[kind]
    mb = MeshBuilder(kind, tone=0.78)
    lm = MeshBuilder(kind + "-lamps", tone=1.0)
    glass = (0.08, 0.11, 0.16)
    flash_z = None

    if kind in ("sedan", "taxi", "police"):
        W = 1.8
        mb.box(-W / 2, -L / 2, 0.30, W / 2, L / 2, 0.95, body)
        mb.box(-W / 2 + 0.1, -L * 0.24, 0.95, W / 2 - 0.1, L * 0.20, 1.38, glass)
        mb.box(-W / 2 + 0.12, -L * 0.26, 1.38, W / 2 - 0.12, L * 0.22, 1.45, body)
        _wheels(mb, W, (-L * 0.32, L * 0.32))
        _lamps(lm, L, W, 0.62)
        if kind == "taxi":
            mb.box(-0.3, -0.15, 1.45, 0.3, 0.15, 1.62, (0.95, 0.85, 0.30))
        if kind == "police":
            for sx in (-1, 1):
                mb.box(sx * W / 2 - 0.02 if sx > 0 else -W / 2 - 0.02, -L * 0.2, 0.45, sx * W / 2 + (0.02 if sx > 0 else 0.02), L * 0.2, 0.9, (0.05, 0.05, 0.07))
            flash_z, fw = 1.45, 0.5
    elif kind == "suv":
        W = 2.0
        mb.box(-W / 2, -L / 2, 0.32, W / 2, L / 2, 1.05, body)
        mb.box(-W / 2 + 0.08, -L * 0.40, 1.05, W / 2 - 0.08, L * 0.28, 1.70, glass)
        mb.box(-W / 2 + 0.1, -L * 0.42, 1.70, W / 2 - 0.1, L * 0.30, 1.78, body)
        _wheels(mb, W, (-L * 0.32, L * 0.32), 0.38)
        _lamps(lm, L, W, 0.70)
    elif kind == "ambulance":
        W = 2.1
        mb.box(-W / 2, -L / 2, 0.35, W / 2, L / 2, 2.45, (0.94, 0.94, 0.95))
        mb.box(-W / 2 + 0.08, L / 2 - 1.4, 1.35, W / 2 - 0.08, L / 2 + 0.01, 2.15, glass)
        for sx in (-1, 1):
            xs = sx * (W / 2 + 0.01)
            mb.box(min(xs, xs - 0.04 * sx), -L / 2 + 0.2, 1.0, max(xs, xs - 0.04 * sx), L / 2 - 1.5, 1.35, (0.80, 0.10, 0.10))
        _wheels(mb, W, (-L * 0.32, L * 0.30), 0.38)
        _lamps(lm, L, W, 0.75)
        flash_z, fw = 2.45, 0.7
    elif kind == "fire":
        W = 2.6
        mb.box(-W / 2, -L / 2, 0.45, W / 2, L / 2 - 2.6, 2.7, (0.74, 0.07, 0.05))
        mb.box(-W / 2, L / 2 - 2.6, 0.45, W / 2, L / 2, 3.0, (0.74, 0.07, 0.05))
        mb.box(-W / 2 + 0.1, L / 2 - 0.02, 1.7, W / 2 - 0.1, L / 2 + 0.02, 2.6, glass)
        mb.box(-0.5, -L / 2 + 0.3, 2.7, 0.5, L / 2 - 2.8, 2.95, (0.85, 0.85, 0.82))    # ladder
        mb.box(-W / 2 - 0.01, -L / 2, 1.2, W / 2 + 0.01, L / 2 - 2.6, 1.4, (0.90, 0.90, 0.88))
        _wheels(mb, W, (-L * 0.30, -L * 0.12, L * 0.33), 0.5)
        _lamps(lm, L, W, 0.85)
        flash_z, fw = 3.0, 0.9
    else:   # bus
        W = 2.55
        mb.box(-W / 2, -L / 2, 0.40, W / 2, L / 2, 1.40, (0.72, 0.09, 0.09))
        mb.box(-W / 2 - 0.01, -L / 2 + 0.2, 1.40, W / 2 + 0.01, L / 2 - 0.2, 2.50, glass)
        mb.box(-W / 2, -L / 2, 2.50, W / 2, L / 2, 3.25, (0.92, 0.92, 0.92))
        _wheels(mb, W, (-L * 0.32, L * 0.30), 0.5)
        _lamps(lm, L, W, 0.8)

    mb.build(root)
    lamp_np = lm.build(root)
    lamp_np.setLightOff()
    if flash_z is not None:
        for name, sx in (("lampA", -1), ("lampB", 1)):
            fm = MeshBuilder(name, tone=1.0)
            fm.box(sx * fw / 2 - 0.22 + (0.0), -0.2, flash_z, sx * fw / 2 + 0.22, 0.2, flash_z + 0.18, (1, 1, 1))
            n = fm.build(root)
            n.setName(name)
            n.setLightOff()
            n.setColor(0.2, 0.2, 0.25, 1)
    root.setScale(CAR_SCALE)
    return root


# ------------------------------------------------------------------------------ signals
SIGNALS = [   # group, pole (x, y), facing (the way the lamps look: toward approaching traffic)
    ("BAY", (3.0, 24.4), (0.0, 1.0)),
    ("BAY", (31.0, 3.6), (0.0, -1.0)),
    ("SJ", (-1.0, 6.0), (-1.0, 0.0)),
    ("SJ", (35.0, 22.0), (1.0, 0.0)),
]
LAMP_ON = {"r": (1.0, 0.12, 0.10, 1), "y": (1.0, 0.75, 0.10, 1), "g": (0.15, 1.0, 0.45, 1)}
LAMP_OFF = (0.12, 0.10, 0.10, 1)


def light_state(group: str, t: float) -> str:
    """Two-phase cycle: Bay green, St Joseph green, with yellow and an all-red clearance each time."""
    t %= CYCLE
    if group == "BAY":
        return "g" if t < 14 else "y" if t < 16 else "r"
    if group == "SJ":
        return "r" if t < 17 else "g" if t < 25 else "y" if t < 27 else "r"
    return "g"


class Car:
    def __init__(self, kind: str, lane: Lane, p: float, v: float, node: NodePath, em: bool) -> None:
        self.kind, self.lane, self.p, self.v, self.node, self.em = kind, lane, p, v, node, em
        self.L = KINDS[kind] * CAR_SCALE
        self.v0 = random.uniform(10.5, 14.0) if not em else random.uniform(17.0, 21.0)
        if kind == "bus":
            self.v0 = random.uniform(8.5, 11.0)
        self.a = 2.0 if not em else 3.2


class Traffic:
    def __init__(self, root: NodePath) -> None:
        self.root = root.attachNewNode("traffic")
        self.t = random.uniform(0, CYCLE)
        self.cars: list[Car] = []
        self._masters: dict = {}
        self._spawn_cd = {id(l): random.uniform(0.0, 2.0) for l in LANES + EM_LANES}
        self._em_cd = random.uniform(8.0, 18.0)
        self._filled = False
        self._flash = 0.0
        self._build_signals()

    # ---------------------------------------------------------------- signals
    def _build_signals(self) -> None:
        self.signals = []
        for group, (px, py), (fx, fy) in SIGNALS:
            node = self.root.attachNewNode("signal")
            node.setPos(px, py, 0)
            node.setH(math.degrees(math.atan2(-fx, fy)))            # +Y is "forward"
            mb = MeshBuilder("pole", tone=0.7)
            mb.cylinder(0, 0, 0, 5.4, 0.12, (0.30, 0.31, 0.33), 8)
            mb.box(-0.30, -0.18, 4.2, 0.30, 0.18, 5.5, (0.08, 0.08, 0.09))
            mb.build(node)
            lamps = []
            for i, z in enumerate((5.15, 4.85, 4.55)):
                lm = MeshBuilder("lamp", tone=1.0)
                lm.ellipsoid(0, 0.2, z, 0.11, 0.06, 0.11, (1, 1, 1), 4, 8)
                ln = lm.build(node)
                ln.setLightOff()
                lamps.append(ln)
            self.signals.append((group, lamps))

    def _set_signals(self) -> None:
        for group, (red, amber, green) in [(g, l) for g, l in self.signals]:
            s = light_state(group, self.t)
            red.setColor(*(LAMP_ON["r"] if s == "r" else LAMP_OFF))
            amber.setColor(*(LAMP_ON["y"] if s == "y" else LAMP_OFF))
            green.setColor(*(LAMP_ON["g"] if s == "g" else LAMP_OFF))

    # ---------------------------------------------------------------- vehicles
    def _make_node(self, kind: str, colour) -> NodePath:
        key = (kind, colour)
        master = self._masters.get(key)
        if master is None:
            master = _build(kind, colour, self.root)
            master.hide()
            self._masters[key] = master
        np = master.copyTo(self.root)
        np.show()
        return np

    def _spawn(self, lane: Lane, p: float, v: float, kind: str | None = None, em: bool = False) -> Car:
        if kind is None:
            r = random.random()
            curb = lane.pos in (8.0, 26.0)
            kind = "bus" if (curb and r < 0.12) else "taxi" if r < 0.22 else "suv" if r < 0.45 else "sedan"
        colour = (0.95, 0.80, 0.15) if kind == "taxi" else (0.94, 0.94, 0.95) if kind in ("ambulance", "police") else \
            (0.74, 0.07, 0.05) if kind == "fire" else random.choice(CAR_COLOURS)
        np = self._make_node(kind, tuple(colour))
        car = Car(kind, lane, p, v, np, em)
        self.cars.append(car)
        self._place(car)
        return car

    @staticmethod
    def _coord(car: Car) -> float:
        return car.lane.dir * car.p

    def _place(self, car: Car) -> None:
        c, ln = self._coord(car), car.lane
        if ln.axis == "y":
            car.node.setPos(ln.pos, c, 0)
            car.node.setH(0 if ln.dir > 0 else 180)
        else:
            car.node.setPos(c, ln.pos, 0)
            car.node.setH(-90 if ln.dir > 0 else 90)

    def _lane_cars(self, lane: Lane) -> list[Car]:
        return sorted((c for c in self.cars if c.lane is lane), key=lambda c: -c.p)

    # ---------------------------------------------------------------- simulation
    def _prefill(self, fx: float, fy: float) -> None:
        for lane in LANES:
            c = fy if lane.axis == "y" else fx
            p = lane.dir * c - WINDOW
            end = lane.dir * c + WINDOW
            while p < end:
                p += random.uniform(16.0, 42.0)
                if p >= end:
                    break
                if lane.stop is not None and abs(lane.dir * lane.stop - p) < 6.0:
                    continue
                self._spawn(lane, p, random.uniform(0, 11.0))
        self._filled = True

    def _idm(self, car: Car, gap: float, vlead: float) -> float:
        b, T, s0 = 3.0, 1.1, 2.0
        dv = car.v - vlead
        s_star = s0 + max(0.0, car.v * T + car.v * dv / (2.0 * math.sqrt(car.a * b)))
        return car.a * (1.0 - (car.v / car.v0) ** 4 - (s_star / max(gap, 0.1)) ** 2)

    def update(self, dt: float, fx: float, fy: float) -> None:
        self.t += dt
        self._flash += dt
        self._set_signals()
        if not self._filled:
            self._prefill(fx, fy)
        if dt <= 0.0:
            return
        dt = min(dt, 0.1)

        # spawning at the upstream edge of the window around the focus
        for lane in LANES + EM_LANES:
            if lane.group == "EM":
                continue
            c = fy if lane.axis == "y" else fx
            p_spawn = lane.dir * c - WINDOW
            self._spawn_cd[id(lane)] -= dt
            if self._spawn_cd[id(lane)] <= 0.0:
                cars = self._lane_cars(lane)
                if not cars or cars[-1].p - cars[-1].L / 2 > p_spawn + 14.0:
                    self._spawn(lane, p_spawn, 11.0)
                    self._spawn_cd[id(lane)] = random.uniform(1.6, 4.5)

        self._em_cd -= dt
        if self._em_cd <= 0.0:
            lane = random.choice(EM_LANES)
            c = fy
            kind = random.choice(["ambulance", "fire", "police", "police"])
            self._spawn(lane, lane.dir * c - WINDOW, 16.0, kind, em=True)
            self._em_cd = random.uniform(30.0, 60.0)

        # car-following (IDM) with signal stop lines
        for lane in LANES + EM_LANES:
            cars = self._lane_cars(lane)
            state = light_state(lane.group, self.t)
            for i, car in enumerate(cars):
                gap, vlead = 1e9, car.v0
                if i > 0:
                    lead = cars[i - 1]
                    gap = (lead.p - lead.L / 2) - (car.p + car.L / 2)
                    vlead = lead.v
                if lane.stop is not None and not car.em and state != "g":
                    dist = lane.dir * lane.stop - (car.p + car.L / 2)
                    stoppable = state == "r" or car.v * car.v / (2.0 * 3.5) <= dist + 0.5
                    if dist > -0.5 and stoppable and dist < gap:
                        gap, vlead = max(dist, 0.1), 0.0
                a = self._idm(car, gap, vlead)
                car.v = max(0.0, car.v + a * dt)
                car.p += car.v * dt

        # remove cars that left the window; flash emergency lights; hide far ones
        keep = []
        for car in self.cars:
            c = self._coord(car)
            f = fy if car.lane.axis == "y" else fx
            if abs(c - f) > WINDOW + 8.0:
                car.node.removeNode()
                continue
            self._place(car)
            ox, oy = car.node.getPos().x - fx, car.node.getPos().y - fy
            if math.hypot(ox, oy) > HIDE_DIST:
                car.node.hide()
            else:
                car.node.show()
            if car.em:
                on_a = int(self._flash * 4) % 2 == 0
                a, b = car.node.find("lampA"), car.node.find("lampB")
                if not a.isEmpty():
                    red, blue = (1.0, 0.10, 0.08, 1), (0.15, 0.30, 1.0, 1)
                    off = (0.15, 0.15, 0.2, 1)
                    first, second = (red, blue) if car.kind != "fire" else (red, (1.0, 0.45, 0.1, 1))
                    a.setColor(*(first if on_a else off))
                    b.setColor(*(second if not on_a else off))
            keep.append(car)
        self.cars = keep
