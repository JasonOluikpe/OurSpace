from __future__ import annotations

import math
from dataclasses import dataclass

from src import layout
from src.collision import Rect
from src.layout import Box, W, WALL_THICK


# Everything here is authored in world metres (see layout.py) and derived from the layout's
# walls so it follows them if the map is rescaled. Furniture is real size x 2 (doors are 1.9 m).
# Local prop frames: origin = footprint centre on the floor, +X right, local -Y is the "front".
HW = WALL_THICK * 0.5


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    h: float = 0.0          # heading in degrees (Panda: counter-clockwise from above)


# ------------------------------------------------------------------------------ room edges
WEST_IN = W(layout.ROOM_L, 0)[0] + HW                       # inner face of the west wall
EAST_IN = W(layout.ROOM_R, 0)[0] - HW
BEDROOM_WEST_IN = W(layout.BEDROOM_WALL, 0)[0] + HW
BEDROOM_SOUTH_IN = W(0, 440)[1] + HW
FRONT_IN = HW

# ------------------------------------------------------------------------------ curtains
CURTAIN_H = 3.90
CURTAIN_COUNT = 4                                   # per room, spread evenly
WALL_Y = W(0, layout.ROOM_T)[1]                     # balcony wall centre line
CURTAIN_Y = WALL_Y - HW - 0.28                      # pleats swing +-0.14 around this
LIVING_OPEN_INDEX = 2                               # 3rd from the left is pulled open

LIVING_X = (WEST_IN, W(layout.BEDROOM_WALL, 0)[0])
BEDROOM_X = (W(layout.BEDROOM_WALL, 0)[0], EAST_IN)


@dataclass(frozen=True)
class Curtain:
    x0: float
    x1: float
    y: float
    opened: bool = False
    room: str = ""


def curtains() -> list[Curtain]:
    out: list[Curtain] = []
    for room, (xa, xb), open_idx in (("living", LIVING_X, LIVING_OPEN_INDEX), ("bedroom", BEDROOM_X, None)):
        w = (xb - xa) / CURTAIN_COUNT
        for i in range(CURTAIN_COUNT):
            out.append(Curtain(xa + i * w, xa + (i + 1) * w, CURTAIN_Y, opened=(i == open_idx), room=room))
    return out


def curtain_fade_box(c: Curtain) -> Box:
    return Box(c.x0, c.y - 0.2, c.x1, c.y + 0.2, 0.0, CURTAIN_H)


# ------------------------------------------------------------------------------ bedroom
BED_HEAD = 2.20                                     # local +Y extent incl. headboard
BED = Placement(EAST_IN - BED_HEAD, 10.70, -90.0)   # headboard against the east wall
BED_LOCAL = (-1.55, -2.03, 1.55, BED_HEAD)
WAND_LOCAL = (-0.75, -0.90)                         # top-left of the bed as seen from above

CRATE_SIZE = (1.6, 2.2, 1.6)                        # bigger and longer; door faces north (the curtains)
CRATE = Placement(BEDROOM_WEST_IN + 0.5 + CRATE_SIZE[0] / 2, BEDROOM_SOUTH_IN + 0.5 + CRATE_SIZE[1] / 2, 180.0)
CRATE_LOCAL = (-CRATE_SIZE[0] / 2, -CRATE_SIZE[1] / 2, CRATE_SIZE[0] / 2, CRATE_SIZE[1] / 2)
TV_LEN = 1.9                                        # long flat screen on top, facing the bed (east)

# ------------------------------------------------------------------------------ living room
SHELF_LEN, SHELF_DEPTH = 2.0, 0.62
SHELF = Placement(WEST_IN + SHELF_DEPTH / 2, 9.78, 90.0)          # open front faces +X
SHELF_LOCAL = (-SHELF_LEN / 2, -SHELF_DEPTH / 2, SHELF_LEN / 2, SHELF_DEPTH / 2)
DESK_LEN, DESK_DEPTH = 1.9, 0.9
DESK = Placement(WEST_IN + DESK_DEPTH / 2, 11.75, 90.0)
DESK_LOCAL = (-DESK_LEN / 2, -DESK_DEPTH / 2, DESK_LEN / 2, DESK_DEPTH / 2)
CHAIR = Placement(WEST_IN + DESK_DEPTH + 0.50, 11.75, -90.0)      # faces the desk (west)
CHAIR_LOCAL = (-0.50, -0.50, 0.50, 0.50)
COUCH_SIZE = (1.7, 2.2)                                            # shrunk, butted up to the shelf
COUCH = Placement(WEST_IN + SHELF_DEPTH + 0.05 + COUCH_SIZE[0] / 2, SHELF.y + 0.10)
COUCH_LOCAL = (-COUCH_SIZE[0] / 2, -COUCH_SIZE[1] / 2, COUCH_SIZE[0] / 2, COUCH_SIZE[1] / 2)

# ------------------------------------------------------------------------------ kitchen
def _counter_geometry():
    horiz, vert = layout.counter_boxes()           # short arm (sink side) and long arm (stove side)
    return horiz, vert


def kitchen_run() -> dict:
    """Only what the photo shows: stove + 3 drawers on the long arm, sink cabinet + dishwasher on the
    short arm, with the stove and sink meeting at the inner corner of the L."""
    horiz, vert = _counter_geometry()
    corner_x, front_y = vert.x1, horiz.y0
    cab_w, dish_w = 1.20, 1.30
    stove_len = 1.50
    stove_y1 = front_y - 0.05
    stove_y0 = stove_y1 - stove_len
    return {
        "front_y": front_y, "back_y": horiz.y1, "top": layout.COUNTER_H,
        "corner_x": corner_x,
        "cabinet": (corner_x, corner_x + cab_w),
        "dishwasher": (corner_x + cab_w, corner_x + cab_w + dish_w),
        "sink_x": corner_x + 1.10, "sink_y": (front_y + horiz.y1) / 2,
        "range_y": (stove_y0, stove_y1),
        "drawers_y": (stove_y0 - 0.06 - 1.20, stove_y0 - 0.06),
    }


FRIDGE_SIZE = (2.40, 2.20, 3.70)
FRIDGE = Placement(W(layout.COUNTER_VERT_X, 0)[0] + 0.08 + FRIDGE_SIZE[0] / 2,
                   FRONT_IN + FRIDGE_SIZE[1] / 2, 180.0)           # front wall, almost touching the counter

# ------------------------------------------------------------------------------ bathroom
BATH_WEST_IN = W(layout.BATH_WALL, 0)[0] + HW
BATH_NORTH_IN = W(0, 440)[1] - HW
TUB_SIZE = (BATH_NORTH_IN - FRONT_IN, 1.55, 1.10)  # wall to wall along the east wall
TUB = Placement(EAST_IN - TUB_SIZE[1] / 2, (BATH_NORTH_IN + FRONT_IN) / 2, -90.0)
VANITY_SIZE = (2.50, 1.20)                         # starts at the west wall, runs along the south wall
VANITY = Placement(BATH_WEST_IN + VANITY_SIZE[0] / 2, FRONT_IN + VANITY_SIZE[1] / 2, 180.0)
TOILET = Placement(4.95, FRONT_IN + 0.70, 180.0)
TOILET_LOCAL = (-0.55, -0.65, 0.55, 0.70)
BATH_RUG = Placement(EAST_IN - TUB_SIZE[1] - 0.05 - 0.65, 3.00)    # black rug beside the tub
BATH_RUG_SIZE = (1.30, 2.00)

# ------------------------------------------------------------------------------ entrance
ENTRY_MAT = Placement((W(layout.FRONT_DOOR_PX, 0)[0] + W(layout.FRONT_DOOR_PX + layout.DX, 0)[0]) / 2, 0.95)
ENTRY_MAT_SIZE = (2.20, 1.40)


# ------------------------------------------------------------------------------ colliders
def _footprint(p: Placement, local, low: bool) -> Rect:
    x0, y0, x1, y1 = local
    a = math.radians(p.h)
    c, s = math.cos(a), math.sin(a)
    pts = [(p.x + x * c - y * s, p.y + x * s + y * c) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    return Rect(min(xs), min(ys), max(xs), max(ys), low=low)


def collider_named() -> list[tuple[str, Rect]]:
    fw, fd, _ = FRIDGE_SIZE
    tw, td, _ = TUB_SIZE
    vw, vd = VANITY_SIZE
    return [
        ("bed", _footprint(BED, BED_LOCAL, True)),
        ("crate", _footprint(CRATE, CRATE_LOCAL, False)),
        ("shelf", _footprint(SHELF, SHELF_LOCAL, True)),
        ("desk", _footprint(DESK, DESK_LOCAL, True)),
        ("chair", _footprint(CHAIR, CHAIR_LOCAL, True)),
        ("couch", _footprint(COUCH, COUCH_LOCAL, True)),
        ("fridge", _footprint(FRIDGE, (-fw / 2, -fd / 2, fw / 2, fd / 2), False)),
        ("tub", _footprint(TUB, (-tw / 2, -td / 2, tw / 2, td / 2), True)),
        ("toilet", _footprint(TOILET, TOILET_LOCAL, True)),
        ("vanity", _footprint(VANITY, (-vw / 2, -vd / 2, vw / 2, vd / 2), False)),
    ]


def collider_rects() -> list[Rect]:
    return [r for _, r in collider_named()]
