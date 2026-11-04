"""Apartment layout: single source of truth for geometry and collision.

Everything is authored in the pixel coordinates of the hand-drawn sketch and
converted to world meters by W(). Both the renderer (world.py) and the
collision system (collision.py) are fed from the functions at the bottom.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
#  Sketch -> world conversion.  Origin = middle of the front wall,
#  +X = right, +Y = toward the balcony.
# --------------------------------------------------------------------------- #
PX_X = 0.105
PX_Y = 0.070
ORIGIN_PX = (615, 537)

DOOR_M = 1.9                  # every doorway (balcony door excepted)
DX = DOOR_M / PX_X
DY = DOOR_M / PX_Y


def W(px: float, py: float) -> tuple[float, float]:
    return ((px - ORIGIN_PX[0]) * PX_X, (ORIGIN_PX[1] - py) * PX_Y)


# Sketch bounds
ROOM_L, ROOM_R = 443, 787
ROOM_T, ROOM_B = 280, 537
BALC_T = 228

WALL_HEIGHT = 4.0
RAIL_HEIGHT = 1.4
WALL_THICK = 0.22
COUNTER_H = 1.6
FENCE_H = 1.4
FLOOR_THICK = 0.10

# Wall segments (px1, py1, px2, py2). Gaps between segments are doorways.
WALLS = [
    # exterior shell
    (443, 537, 625, 537),
    (625 + DX, 537, 787, 537),
    (443, 280, 443, 537),
    (787, 280, 787, 537),
    (443, 280, 480, 280),          # balcony divider, left of sliding door
    (570, 280, 787, 280),          # balcony divider, right of sliding door
    # bedroom
    (629, 280 + DY, 629, 440),
    (629, 440, 728, 440),
    (728 + DX, 440, 787, 440),
    # bathroom
    (688, 440, 688, 479 - DY / 2),
    (688, 479 + DY / 2, 688, 537),
    # closet
    (541, 480, 541, 537),
    (541, 480, 587, 480),
    (587, 480, 587, 497),
    (587, 497 + DY, 587, 537),
]

RAILS = [
    (443, 228, 443, 280),
    (787, 228, 787, 280),
    (443, 228, 787, 228),
]

FENCE = (560, 629, 396)            # px x1, x2, y

COUNTER = [
    (443, 375, 560, 417),
    (443, 375, 487, 537),
]

LABELS = (
    ("LIVING ROOM", 515, 325, 1.00),
    ("KITCHEN",     535, 450, 0.65),
    ("BEDROOM",     710, 365, 1.00),
    ("BATHROOM",    738, 490, 0.75),
    ("CLOSET",      564, 515, 0.48),
    ("ENTRY",       645, 500, 0.60),
    ("BALCONY",     615, 258, 1.00),
)

SPAWN_PX = (645, 505)


# --------------------------------------------------------------------------- #
#  Derived geometry (world meters)
# --------------------------------------------------------------------------- #
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


def fence_boxes() -> list[Box]:
    """Visual parts of the dog fence: rails + pickets."""
    px1, px2, py = FENCE
    xa, y = W(px1, py)
    xb, _ = W(px2, py)
    t = 0.10
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
        parts.append(Box(max(xa, cx - pw / 2), y0, min(xb, cx + pw / 2), y1,
                         0.0, FENCE_H))
    return parts


def fence_collider() -> Box:
    px1, px2, py = FENCE
    xa, y = W(px1, py)
    xb, _ = W(px2, py)
    return Box(xa, y - 0.05, xb, y + 0.05, 0.0, FENCE_H)


def floor_box() -> Box:
    x0, y1 = W(ROOM_L, ROOM_T)
    x1, y0 = W(ROOM_R, ROOM_B)
    return Box(x0, y0, x1, y1, -FLOOR_THICK, 0.0)


def balcony_box() -> Box:
    x0, y1 = W(ROOM_L, BALC_T)
    x1, y0 = W(ROOM_R, ROOM_T)
    return Box(x0, y0, x1, y1, -FLOOR_THICK, 0.0)


def walkable_bounds() -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) of the whole floor incl. balcony."""
    x0, y_top = W(ROOM_L, BALC_T)
    x1, y_bot = W(ROOM_R, ROOM_B)
    return x0, y_bot, x1, y_top


def collider_boxes() -> list[Box]:
    return (wall_boxes() + rail_boxes() + counter_boxes() + [fence_collider()])


def spawn_point() -> tuple[float, float]:
    return W(*SPAWN_PX)


# --------------------------------------------------------------------------- #
#  Doors
# --------------------------------------------------------------------------- #
DOOR_HEIGHT = WALL_HEIGHT
DOOR_THICK = 0.12
SLIDE_OFFSET = 0.17          # sliding panels sit beside the wall, not in it


@dataclass(frozen=True)
class DoorSpec:
    name: str
    kind: str                          # "swing" | "slide"
    a: tuple[float, float]             # opening start (world xy)
    b: tuple[float, float]             # opening end   (world xy)
    # swing
    hinge_at_b: bool = False           # hinge at b (else at a)
    open_normal: tuple[float, float] = (0.0, 1.0)   # side the leaf swings toward
    # slide
    slide_toward_b: bool = True
    slide_offset: tuple[float, float] = (0.0, 0.0)  # panel offset from wall centre-line
    glass: bool = False
    duration: float = 0.7              # seconds to fully open / close


def _opening(p0, p1):
    """Sketch-pixel gap -> world opening, trimmed by the wall-end overhang."""
    a, b = W(*p0), W(*p1)
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    h = WALL_THICK * 0.5
    return (a[0] + ux * h, a[1] + uy * h), (b[0] - ux * h, b[1] - uy * h)


def door_specs() -> list[DoorSpec]:
    """The front door / entry has no door."""
    specs = []

    # bathroom: hinge at the south end, swings INTO the bathroom (east)
    a, b = _opening((688, 479 - DY / 2), (688, 479 + DY / 2))
    specs.append(DoorSpec("bathroom", "swing", a, b, hinge_at_b=True,
                          open_normal=(1.0, 0.0)))

    # closet: swings OUT toward the entry (east)
    a, b = _opening((587, 497), (587, 497 + DY))
    specs.append(DoorSpec("closet", "swing", a, b, hinge_at_b=True,
                          open_normal=(1.0, 0.0)))

    # lower bedroom door: swings INTO the bedroom (north)
    a, b = _opening((728, 440), (728 + DX, 440))
    specs.append(DoorSpec("bedroom_lower", "swing", a, b, hinge_at_b=True,
                          open_normal=(0.0, 1.0)))

    # upper bedroom door: slides south along the wall, on the bedroom side
    a, b = _opening((629, 280), (629, 280 + DY))
    specs.append(DoorSpec("bedroom_upper", "slide", a, b, slide_toward_b=True,
                          slide_offset=(SLIDE_OFFSET, 0.0), duration=1.0))

    # balcony: big glass slider, slides east along the divider on the balcony side
    a, b = _opening((480, 280), (570, 280))
    specs.append(DoorSpec("balcony", "slide", a, b, slide_toward_b=True,
                          slide_offset=(0.0, SLIDE_OFFSET), glass=True,
                          duration=1.6))
    return specs