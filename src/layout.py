from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# The layout is authored in pixels of the hand-drawn sketch; W() converts to meters.
# World origin: middle of the front wall. +X = right, +Y = toward the balcony.
PX_X = 0.063      # smaller, tighter apartment (was 0.105 / 0.070)
PX_Y = 0.052
ORIGIN_PX = (615, 537)

DOOR_M = 1.9
DX = DOOR_M / PX_X
DY = DOOR_M / PX_Y

# Living-room balcony door (px along the balcony wall). It sits behind the 3rd of the 4 curtains.
BALC_DOOR_PX = (525, 555)


def W(px: float, py: float) -> tuple[float, float]:
    return ((px - ORIGIN_PX[0]) * PX_X, (ORIGIN_PX[1] - py) * PX_Y)


ROOM_L, ROOM_R = 443, 733
ROOM_T, ROOM_B = 280, 537
BALC_T = 228

WALL_HEIGHT = 4.0
RAIL_HEIGHT = 1.4
WALL_THICK = 0.22
COUNTER_H = 1.6
FENCE_H = 1.4
FLOOR_THICK = 0.10

# Key x positions (px). The entrance row along the front wall is deliberately tight:
#   counter | fridge | closet | front door | bathroom wall
CLOSET_W, CLOSET_E, CLOSET_N = 517, 566, 490
FRONT_DOOR_PX = 588
BEDROOM_WALL = 590
BATH_WALL = 640
BED_BATH_DOOR_PX = 655
GATE_PX = (526, BEDROOM_WALL, 396)
COUNTER_VERT_X = 475
COUNTER_ARM_END = 526

# Gaps between segments are doorways. The front entrance deliberately has no door.
WALLS = [
    (443, 537, FRONT_DOOR_PX, 537),
    (FRONT_DOOR_PX + DX, 537, ROOM_R, 537),
    (443, 280, 443, 537),
    (ROOM_R, 280, ROOM_R, 537),
    (443, 280, BALC_DOOR_PX[0], 280),
    (BALC_DOOR_PX[1], 280, ROOM_R, 280),
    (BEDROOM_WALL, 280 + DY, BEDROOM_WALL, 440),
    (BEDROOM_WALL, 440, BED_BATH_DOOR_PX, 440),
    (BED_BATH_DOOR_PX + DX, 440, ROOM_R, 440),
    (BATH_WALL, 440, BATH_WALL, 478 - DY / 2),
    (BATH_WALL, 478 + DY / 2, BATH_WALL, 537),
    (CLOSET_W, CLOSET_N, CLOSET_W, 537),               # closet: thin, tucked right beside the fridge
    (CLOSET_W, CLOSET_N, CLOSET_E, CLOSET_N),
    (CLOSET_E, CLOSET_N, CLOSET_E, 496),
    (CLOSET_E, 496 + DY, CLOSET_E, 537),
]

RAILS = [
    (443, 228, 443, 280),
    (ROOM_R, 228, ROOM_R, 280),
    (443, 228, ROOM_R, 228),
]

FENCE = GATE_PX

COUNTER = [
    (443, 375, COUNTER_ARM_END, 417),
    (443, 375, COUNTER_VERT_X, 537),
]

LABELS = (
    ("LIVING ROOM", 510, 322, 1.00),
    ("KITCHEN",     520, 452, 0.65),
    ("BEDROOM",     665, 360, 1.00),
    ("BATHROOM",    690, 505, 0.75),
    ("CLOSET",      541, 516, 0.48),
    ("ENTRY",       603, 500, 0.60),
    ("BALCONY",     590, 258, 1.00),
)

SPAWN_PX = (505, 335)
ANNA_SPAWN_PX = (540, 345)
OUTSIDE_DEPTH = 9.0


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    z0: float
    z1: float


def _wall_box(seg, height) -> Box:
    (ax, ay), (bx, by) = W(seg[0], seg[1]), W(seg[2], seg[3])
    h = WALL_THICK * 0.5
    return Box(min(ax, bx) - h, min(ay, by) - h,
               max(ax, bx) + h, max(ay, by) + h, 0.0, height)


def wall_boxes() -> list[Box]:
    return [_wall_box(s, WALL_HEIGHT) for s in WALLS]


def rail_boxes() -> list[Box]:
    return [_wall_box(s, RAIL_HEIGHT) for s in RAILS]


def counter_boxes() -> list[Box]:
    out = []
    for px1, py1, px2, py2 in COUNTER:
        ax, ay = W(px1, py1)
        bx, by = W(px2, py2)
        out.append(Box(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by),
                       0.0, COUNTER_H))
    return out


GATE_LEAF_M = DOOR_M      # width of the swinging leaf
GATE_T = 0.10             # bar thickness
GATE_POST = 0.14          # leaf end posts


@dataclass(frozen=True)
class GateSpec:
    y: float              # centre line
    x0: float             # west end (counter side)
    x1: float             # east end (bedroom wall)
    hinge_x: float        # leaf pivot, tucked against the bedroom wall
    leaf_len: float

    @property
    def free_x(self) -> float:
        return self.hinge_x - self.leaf_len


def gate_spec() -> GateSpec:
    px1, px2, py = FENCE
    xa, y = W(px1, py)
    xb, _ = W(px2, py)
    hinge = xb - WALL_THICK * 0.5 - GATE_T * 0.5
    return GateSpec(y=y, x0=xa, x1=xb, hinge_x=hinge, leaf_len=GATE_LEAF_M)


def gate_panel_boxes(xa: float, xb: float, y: float, posts: tuple[bool, bool] = (False, False)) -> list[Box]:
    """Rails + pickets for one gate panel, centred on `y`."""
    t = GATE_T
    y0, y1 = y - t / 2, y + t / 2
    parts = [
        Box(xa, y0, xb, y1, 0.15, 0.30),
        Box(xa, y0, xb, y1, FENCE_H - 0.20, FENCE_H),
        Box(xa, y0, xb, y1, FENCE_H * 0.5 - 0.075, FENCE_H * 0.5 + 0.075),
    ]
    n = max(2, int((xb - xa) / 0.55))
    pw = 0.10
    for i in range(n + 1):
        cx = xa + (xb - xa) * i / n
        if (i == 0 and posts[0]) or (i == n and posts[1]):
            pw_i = GATE_POST
        else:
            pw_i = pw
        parts.append(Box(max(xa, cx - pw_i / 2), y0, min(xb, cx + pw_i / 2), y1, 0.0, FENCE_H))
    return parts


def fence_boxes() -> list[Box]:
    """Fixed (non-swinging) part of the gate, world coordinates."""
    g = gate_spec()
    return gate_panel_boxes(g.x0, g.free_x - 0.03, g.y, posts=(False, True))


def gate_leaf_boxes() -> list[Box]:
    """Swinging leaf, authored in leaf-local space: hinge at the origin, leaf along local -X."""
    g = gate_spec()
    return gate_panel_boxes(-g.leaf_len, 0.0, 0.0, posts=(True, True))


def fence_collider() -> Box:
    g = gate_spec()
    return Box(g.x0, g.y - 0.05, g.x1, g.y + 0.05, 0.0, FENCE_H)


def floor_box() -> Box:
    x0, y1 = W(ROOM_L, ROOM_T)
    x1, y0 = W(ROOM_R, ROOM_B)
    return Box(x0, y0, x1, y1, -FLOOR_THICK, 0.0)


BATH_L, BATH_R = BATH_WALL, ROOM_R      # bathroom px extents (see WALLS)
BATH_T, BATH_B = 440, 537


def bathroom_box() -> Box:
    x0, y1 = W(BATH_L, BATH_T)
    x1, y0 = W(BATH_R, BATH_B)
    return Box(x0, y0, x1, y1, -FLOOR_THICK, 0.0)


def plank_floor_boxes() -> list[Box]:
    """Room floor minus the bathroom (which is tiled): two rectangles."""
    room, bath = floor_box(), bathroom_box()
    return [
        Box(room.x0, room.y0, bath.x0, room.y1, room.z0, room.z1),
        Box(bath.x0, bath.y1, room.x1, room.y1, room.z0, room.z1),
    ]


def balcony_box() -> Box:
    x0, y1 = W(ROOM_L, BALC_T)
    x1, y0 = W(ROOM_R, ROOM_T)
    return Box(x0, y0, x1, y1, -FLOOR_THICK, 0.0)


def walkable_bounds() -> tuple[float, float, float, float]:
    x0, y_top = W(ROOM_L, BALC_T)
    x1, y_bot = W(ROOM_R, ROOM_B)
    return x0, y_bot, x1, y_top


def collider_boxes() -> list[Box]:
    return wall_boxes() + rail_boxes() + counter_boxes()


def spawn_point() -> tuple[float, float]:
    return W(*SPAWN_PX)


def anna_spawn_point() -> tuple[float, float]:
    return W(*ANNA_SPAWN_PX)


def agent_bounds() -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = walkable_bounds()
    return x0, y0 - OUTSIDE_DEPTH, x1, y1


def front_door_center() -> tuple[float, float]:
    x, _ = W(FRONT_DOOR_PX + DX / 2, 537)
    return x, 0.0


def outside_box() -> Box:
    x0, y0, x1, _ = agent_bounds()
    return Box(x0, y0, x1, 0.0, -FLOOR_THICK, 0.0)


FROSTED_GLASS = (0.80, 0.90, 0.86, 0.62)   # translucent bedroom sliding door

DOOR_HEIGHT = WALL_HEIGHT
DOOR_THICK = 0.12
SLIDE_OFFSET = 0.17


@dataclass(frozen=True)
class DoorSpec:
    name: str
    kind: str
    a: tuple[float, float]
    b: tuple[float, float]
    hinge_at_b: bool = False
    open_normal: tuple[float, float] = (0.0, 1.0)
    slide_toward_b: bool = True
    slide_offset: tuple[float, float] = (0.0, 0.0)
    glass: bool = False
    duration: float = 0.7
    colour: Optional[tuple[float, float, float, float]] = None


def _opening(p0, p1):
    a, b = W(*p0), W(*p1)
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    h = WALL_THICK * 0.5
    return (a[0] + ux * h, a[1] + uy * h), (b[0] - ux * h, b[1] - uy * h)


def door_specs() -> list[DoorSpec]:
    specs = []

    a, b = _opening((BATH_WALL, 478 - DY / 2), (BATH_WALL, 478 + DY / 2))
    specs.append(DoorSpec("bathroom", "swing", a, b, hinge_at_b=True, open_normal=(1.0, 0.0)))

    # closet door hinges at its north edge so the open leaf doesn't block the front doorway
    a, b = _opening((CLOSET_E, 496), (CLOSET_E, 496 + DY))
    specs.append(DoorSpec("closet", "swing", a, b, hinge_at_b=False, open_normal=(1.0, 0.0)))

    a, b = _opening((BED_BATH_DOOR_PX, 440), (BED_BATH_DOOR_PX + DX, 440))
    specs.append(DoorSpec("bedroom_lower", "swing", a, b, hinge_at_b=True, open_normal=(0.0, 1.0)))

    a, b = _opening((BEDROOM_WALL, 280), (BEDROOM_WALL, 280 + DY))
    specs.append(DoorSpec("bedroom_upper", "slide", a, b, slide_toward_b=True, slide_offset=(SLIDE_OFFSET, 0.0),
                          glass=True, duration=1.0, colour=FROSTED_GLASS))

    a, b = _opening((BALC_DOOR_PX[0], 280), (BALC_DOOR_PX[1], 280))
    specs.append(DoorSpec("balcony", "slide", a, b, slide_toward_b=True, slide_offset=(0.0, SLIDE_OFFSET), glass=True, duration=1.6))
    return specs
