from __future__ import annotations

import math

from panda3d.core import NodePath, TransparencyAttrib

from src import furniture as F
from src import layout
from src.layout import Box
from src.meshes import MeshBuilder

# Albedo palette (MeshBuilder darkens these to suit the scene lighting).
WHITE = (0.96, 0.96, 0.95, 1)
OFFWHITE = (0.90, 0.89, 0.86, 1)
STEEL = (0.74, 0.75, 0.77, 1)
STEEL_LIGHT = (0.80, 0.81, 0.83, 1)
CHROME = (0.90, 0.92, 0.95, 1)
BLACK = (0.10, 0.10, 0.11, 1)
CHARCOAL = (0.17, 0.17, 0.18, 1)
CABINET = (0.20, 0.17, 0.15, 1)
CABINET_FRONT = (0.29, 0.25, 0.22, 1)
COUNTER_TOP = (0.97, 0.97, 0.96, 1)
MARBLE = (0.90, 0.90, 0.89, 1)
OAK = (0.52, 0.48, 0.44, 1)
BLUE_DUVET = (0.36, 0.52, 0.74, 1)
BLUE_DUVET_LIGHT = (0.45, 0.61, 0.82, 1)
CURTAIN_GREY = (0.56, 0.54, 0.51, 1)


def _place(np: NodePath, p: F.Placement) -> NodePath:
    np.setPos(p.x, p.y, 0.0)
    np.setH(p.h)
    return np


def _rects_minus_hole(rect, hole):
    x0, y0, x1, y1 = rect
    hx0, hy0, hx1, hy1 = hole
    return [(x0, y0, hx0, y1), (hx1, y0, x1, y1), (hx0, y0, hx1, hy0), (hx0, hy1, hx1, y1)]


def _basin(mb: MeshBuilder, hole, z0: float, z1: float, colour, floor_colour=None, t: float = 0.04) -> None:
    hx0, hy0, hx1, hy1 = hole
    mb.box(hx0, hy0, z0, hx1, hy1, z0 + t, floor_colour or colour)
    mb.box(hx0, hy0, z0, hx0 + t, hy1, z1, colour)
    mb.box(hx1 - t, hy0, z0, hx1, hy1, z1, colour)
    mb.box(hx0, hy0, z0, hx1, hy0 + t, z1, colour)
    mb.box(hx0, hy1 - t, z0, hx1, hy1, z1, colour)
    cx, cy = (hx0 + hx1) / 2, (hy0 + hy1) / 2
    mb.cylinder(cx, cy, z0 + t, z0 + t + 0.01, 0.07, (0.25, 0.25, 0.27, 1), 14)


def _gooseneck(mb: MeshBuilder, x: float, y: float, z: float, reach: float, rise: float, r: float,
               direction: float = -1.0) -> None:
    """Chrome arched faucet. `direction` = which way (+-Y) the spout reaches."""
    mb.cylinder(x, y, z, z + 0.10, r * 1.8, CHROME, 14)
    top = z + rise
    pts = [(x, y, z + 0.08), (x, y, top)]
    steps = 8
    rad = reach / 2
    for i in range(1, steps + 1):
        a = math.pi * i / steps
        pts.append((x, y + direction * (rad - rad * math.cos(a)), top + rad * math.sin(a)))
    pts.append((x, y + direction * reach, top - 0.30))
    mb.tube(pts, r, CHROME, 8)
    mb.cyl_between((x + 0.10, y, z + 0.10), (x + 0.42, y, z + 0.30), r * 0.55, CHROME, 8)   # lever


def _handle_bar_x(mb: MeshBuilder, x0, x1, y_face, z, out: float = 0.11, r: float = 0.028) -> None:
    """Horizontal pull on a face whose normal is -Y."""
    mb.cyl_between((x0, y_face - out, z), (x1, y_face - out, z), r, STEEL_LIGHT, 8)
    for x in (x0 + 0.04, x1 - 0.04):
        mb.cyl_between((x, y_face, z), (x, y_face - out, z), r * 0.8, STEEL_LIGHT, 6)


def _handle_bar_z(mb: MeshBuilder, x, y_face, z0, z1, out: float = 0.11, r: float = 0.028) -> None:
    mb.cyl_between((x, y_face - out, z0), (x, y_face - out, z1), r, STEEL_LIGHT, 8)
    for z in (z0 + 0.04, z1 - 0.04):
        mb.cyl_between((x, y_face, z), (x, y_face - out, z), r * 0.8, STEEL_LIGHT, 6)


# =========================================================================================
# Bedroom
# =========================================================================================
def build_bed(parent: NodePath) -> NodePath:
    mb = MeshBuilder("bed")
    mb.box(-1.48, -1.98, 0.10, 1.48, 2.00, 0.55, (0.24, 0.24, 0.26, 1))              # platform base
    mb.box(-1.52, -2.00, 0.55, 1.52, 1.98, 1.05, OFFWHITE)                           # mattress
    mb.box(-1.56, -2.04, 0.60, 1.56, 1.15, 1.14, BLUE_DUVET)                         # blue covers
    mb.box(-1.56, 1.10, 0.64, 1.56, 1.42, 1.17, BLUE_DUVET_LIGHT)                    # folded-over edge
    for x0, x1, c in ((-1.46, -0.50, WHITE), (-0.48, 0.48, WHITE), (0.50, 1.46, (0.50, 0.64, 0.82, 1))):
        mb.box(x0, 1.50, 1.05, x1, 1.95, 1.30, c)                                    # 3 pillows: white, white, blue
    mb.box(-1.60, 1.98, 0.10, 1.60, 2.20, 2.00, (0.52, 0.52, 0.55, 1))               # headboard (head = +Y)

    # the inside joke: a wand lying on the top-left of the covers
    wx, wy = F.WAND_LOCAL
    with mb.at(wx, wy, 1.14 + 0.06, h=-28):
        mb.cyl_between((0, -0.46, 0), (0, 0.10, 0), 0.055, WHITE, 12)                # handle
        mb.cyl_between((0, -0.26, 0), (0, -0.14, 0), 0.060, (0.35, 0.60, 0.50, 1), 12)  # button band
        mb.cyl_between((0, 0.10, 0), (0, 0.22, 0), 0.055, WHITE, 12, r1=0.085)           # neck
        mb.ellipsoid(0, 0.33, 0, 0.15, 0.15, 0.15, (0.88, 0.90, 0.88, 1), 8, 14)         # head
    return mb.build(parent)


def _wire_door(mb: MeshBuilder, w: float, h: float) -> None:
    """Dog-crate door authored along local -X from its hinge; wire mesh + wooden frame."""
    wood = (0.34, 0.31, 0.28, 1)
    mesh = (0.07, 0.07, 0.08, 1)
    t = 0.06
    mb.box(-w, -0.03, 0, 0, 0.03, t, wood)
    mb.box(-w, -0.03, h - t, 0, 0.03, h, wood)
    mb.box(-w, -0.03, 0, -w + t, 0.03, h, wood)
    mb.box(-t, -0.03, 0, 0, 0.03, h, wood)
    n = 7
    for i in range(1, n):
        x = -w * i / n
        mb.box(x - 0.012, -0.012, t, x + 0.012, 0.012, h - t, mesh)
    for k in range(1, 5):
        z = h * k / 5
        mb.box(-w + t, -0.012, z - 0.012, -t, 0.012, z + 0.012, mesh)


def build_crate(parent: NodePath) -> NodePath:
    """Wooden dog-crate cabinet, door on the front (-Y) with a long flat-screen TV on top.
    Placed so the door faces the curtains and the TV screen faces the bed."""
    W, D, H = F.CRATE_SIZE
    hw, hd = W / 2, D / 2
    mb = MeshBuilder("dog_crate")
    dark = (0.12, 0.11, 0.11, 1)
    t = 0.12
    mb.box(-hw, -hd, 0.14, hw, hd, 0.26, OAK)                                        # floor
    mb.box(-hw, -hd, H - 0.12, hw, hd, H, OAK)                                       # top
    mb.box(-hw, -hd, 0.14, -hw + t, hd, H, OAK)                                      # sides
    mb.box(hw - t, -hd, 0.14, hw, hd, H, OAK)
    mb.box(-hw + t, hd - t, 0.26, hw - t, hd, H - 0.12, dark)                        # back
    for sx in (-hw + 0.15, hw - 0.15):
        for sy in (-hd + 0.15, hd - 0.15):
            mb.cylinder(sx, sy, 0.0, 0.14, 0.06, (0.40, 0.40, 0.42, 1), 10)           # feet
    with mb.at(hw - t, -hd, 0.26, h=100):                                            # wire door, swung open
        _wire_door(mb, W - 2 * t, H - 0.38)

    # long flat-screen TV on top, screen facing -X (local) = toward the bed once the crate is placed
    z0 = H
    mb.box(-0.30, -0.40, z0, 0.30, 0.40, z0 + 0.05, CHARCOAL)                         # stand base
    mb.box(-0.04, -0.06, z0 + 0.05, 0.04, 0.06, z0 + 0.30, CHARCOAL)
    tv_z0, tv_z1 = z0 + 0.22, z0 + 1.12
    mb.box(-0.05, -TV_HALF, tv_z0, 0.05, TV_HALF, tv_z1, (0.05, 0.05, 0.06, 1))     # panel
    mb.quad((-0.052, -TV_HALF + 0.05, tv_z0 + 0.05), (-0.052, TV_HALF - 0.05, tv_z0 + 0.05),
            (-0.052, TV_HALF - 0.05, tv_z1 - 0.05), (-0.052, -TV_HALF + 0.05, tv_z1 - 0.05),
            (0.10, 0.13, 0.19, 1), (-1, 0, 0))
    return mb.build(parent)


TV_HALF = F.TV_LEN / 2


# =========================================================================================
# Living room
# =========================================================================================
def build_desk(parent: NodePath) -> NodePath:
    mb = MeshBuilder("desk")
    top = (0.09, 0.09, 0.10, 1)
    L, D = F.DESK_LEN / 2, F.DESK_DEPTH / 2
    mb.box(-L, -D, 1.40, L, D, 1.50, top)
    for sx in (-L + 0.04, L - 0.04):
        for sy in (-D + 0.04, D - 0.04):
            mb.box(sx - 0.035, sy - 0.035, 0.0, sx + 0.035, sy + 0.035, 1.40, top)
    mb.box(-L + 0.04, D - 0.07, 0.90, L - 0.04, D - 0.01, 0.96, top)                 # back rail
    for sx in (-L + 0.04, L - 0.04):
        mb.box(sx - 0.03, -D + 0.04, 0.90, sx + 0.03, D - 0.04, 0.96, top)           # side rails

    with mb.at(0.15, 0.12, 1.50):                                                    # monitor
        mb.box(-0.28, -0.17, 0.0, 0.28, 0.17, 0.04, CHARCOAL)
        mb.box(-0.05, -0.03, 0.04, 0.05, 0.05, 0.40, CHARCOAL)
        mb.box(-0.50, -0.05, 0.38, 0.50, 0.05, 0.98, (0.07, 0.07, 0.08, 1))
        mb.quad((-0.46, -0.052, 0.42), (0.46, -0.052, 0.42), (0.46, -0.052, 0.94), (-0.46, -0.052, 0.94),
                (0.17, 0.23, 0.32, 1), (0, -1, 0))

    cx = -L + 0.42                                                                   # CPU tower on the floor
    mb.box(cx - 0.19, -0.40, 0.0, cx + 0.19, 0.40, 0.86, (0.10, 0.10, 0.11, 1))
    mb.box(cx - 0.17, -0.405, 0.08, cx + 0.17, -0.40, 0.80, (0.15, 0.15, 0.16, 1))
    mb.box(cx - 0.04, -0.41, 0.70, cx + 0.04, -0.40, 0.73, (0.35, 0.75, 0.45, 1))    # tiny power LED
    return mb.build(parent)


def build_chair(parent: NodePath) -> NodePath:
    mb = MeshBuilder("ergonomic_chair")
    b = (0.10, 0.10, 0.11, 1)
    frame = (0.07, 0.07, 0.08, 1)
    mesh = (0.18, 0.18, 0.19, 1)
    for i in range(5):                                                               # five-star base + casters
        a = math.radians(72 * i + 18)
        dx, dy = math.cos(a), math.sin(a)
        mb.cyl_between((0, 0, 0.20), (0.56 * dx, 0.56 * dy, 0.16), 0.05, frame, 8)
        mb.cylinder(0.56 * dx, 0.56 * dy, 0.0, 0.14, 0.07, frame, 10)
    mb.cylinder(0, 0, 0.18, 0.88, 0.06, (0.30, 0.30, 0.32, 1), 10)                   # gas lift
    mb.cylinder(0, 0, 0.82, 0.92, 0.20, b, 14)
    mb.box(-0.48, -0.46, 0.90, 0.48, 0.46, 1.04, b)                                  # seat
    mb.box(-0.06, 0.34, 0.96, 0.06, 0.42, 1.30, frame)                               # back support
    mb.box(-0.46, 0.40, 1.10, 0.46, 0.50, 2.15, frame)                               # backrest frame
    mb.box(-0.40, 0.385, 1.16, 0.40, 0.40, 2.09, mesh)                               # mesh panel
    for sx in (-0.53, 0.53):                                                         # arms
        mb.box(sx - 0.03, 0.04, 1.04, sx + 0.03, 0.12, 1.45, frame)
        mb.box(sx - 0.06, -0.32, 1.45, sx + 0.06, 0.32, 1.52, b)
    return mb.build(parent)


def build_shelf(parent: NodePath) -> NodePath:
    """Low white cubby unit: 4 open compartments with fabric bins."""
    mb = MeshBuilder("storage_shelf")
    L, D, H, t = F.SHELF_LEN, F.SHELF_DEPTH, 0.78, 0.06
    cell = (L - 5 * t) / 4
    mb.box(-L / 2, -D / 2, 0.0, L / 2, D / 2, t, WHITE)
    mb.box(-L / 2, -D / 2, H - t, L / 2, D / 2, H, WHITE)
    for i in range(5):
        x = -L / 2 + i * (cell + t)
        mb.box(x, -D / 2, 0.0, x + t, D / 2, H, WHITE)
    mb.box(-L / 2, D / 2 - 0.02, 0.0, L / 2, D / 2, H, (0.84, 0.84, 0.83, 1))
    bins = [OFFWHITE, (0.80, 0.80, 0.78, 1), (0.52, 0.62, 0.76, 1), OFFWHITE]
    for i, c in enumerate(bins):
        x0 = -L / 2 + t + i * (cell + t) + 0.035
        mb.box(x0, -D / 2 + 0.05, t, x0 + cell - 0.07, D / 2 - 0.05, H - t - 0.03, c)
    return mb.build(parent)


def build_couch(parent: NodePath) -> NodePath:
    """The 'couch': a bed with a heap of laundry on it (shrunk to fit beside the storage unit)."""
    cw, cl = F.COUCH_SIZE
    mb = MeshBuilder("couch_bed_laundry")
    mb.box(-cw / 2, -cl / 2, 0.0, cw / 2, cl / 2, 0.45, (0.93, 0.90, 0.80, 1))        # mattress + sheet
    base = 0.45
    kx, ky = cw / 2.0, cl / 3.6                                                      # lump layout was authored for 2.0 x 3.6
    lumps = [   # centre x, y, z-above-base, radii, colour
        (-0.30, -0.90, 0.17, (0.85, 0.95, 0.20), (0.55, 0.66, 0.80, 1)),   # blue blanket
        (0.35, -0.15, 0.24, (0.70, 0.60, 0.28), (0.12, 0.14, 0.26, 1)),    # navy hoodie pile
        (-0.30, 0.70, 0.28, (0.60, 0.55, 0.32), (0.10, 0.10, 0.11, 1)),    # dark clothes
        (0.40, 1.28, 0.22, (0.55, 0.38, 0.24), (0.66, 0.67, 0.69, 1)),     # grey pillows
        (-0.62, 0.05, 0.40, (0.28, 0.32, 0.14), (0.92, 0.58, 0.68, 1)),    # something pink
        (0.62, -1.12, 0.26, (0.34, 0.30, 0.13), (0.92, 0.92, 0.90, 1)),    # something white
        (0.12, -0.62, 0.42, (0.40, 0.34, 0.15), (0.28, 0.40, 0.66, 1)),    # jeans
    ]
    for x, y, z, r, c in lumps:
        mb.ellipsoid(x * kx, y * ky, base + z, r[0] * kx, r[1] * ky, r[2], c, 7, 12)
    return mb.build(parent)


# =========================================================================================
# Curtains
# =========================================================================================
def build_curtain(parent: NodePath, c: F.Curtain) -> NodePath:
    mb = MeshBuilder("curtain", tone=0.80)
    if c.opened:                                    # pulled open: bunched against the left edge of its span
        x0, x1, amp, wl = c.x0 + 0.02, c.x0 + 0.52, 0.22, 0.25
    else:
        x0, x1, amp, wl = c.x0 + 0.02, c.x1 - 0.02, 0.14, 0.60
    cols = max(8, int((x1 - x0) / (wl / 8)) + 1)
    zs = [0.02, 0.8, 1.6, 2.4, 3.2, F.CURTAIN_H]
    grid, colours = [], []
    for z in zs:
        depth = amp * (0.82 + 0.28 * (1.0 - z / F.CURTAIN_H))
        row, crow = [], []
        for j in range(cols):
            x = x0 + (x1 - x0) * j / (cols - 1)
            ph = 2 * math.pi * (x - x0) / wl
            row.append((x, c.y + depth * math.sin(ph), z))
            s = (0.80 + 0.20 * math.cos(ph)) * (0.90 + 0.10 * z / F.CURTAIN_H)
            crow.append((CURTAIN_GREY[0] * s, CURTAIN_GREY[1] * s, CURTAIN_GREY[2] * s, 1.0))
        grid.append(row)
        colours.append(crow)
    mb.sheet(grid, colours)
    np = mb.build(parent)
    np.setTwoSided(True)
    return np


# =========================================================================================
# Kitchen
# =========================================================================================
def build_kitchen(parent: NodePath) -> NodePath:
    """Completes the L-shaped counter with only what the photo shows: the stove + oven and 3 drawers
    on the long arm, the sink + cabinet + dishwasher on the short arm. Stove and sink meet at the
    inner corner of the L."""
    K = F.kitchen_run()
    horiz, vert = layout.counter_boxes()
    top = K["top"]
    y0, y1 = K["front_y"], K["back_y"]
    slab_z0 = top - 0.08
    mb = MeshBuilder("kitchen")

    arm = (vert.x1, horiz.y0, horiz.x1, horiz.y1)          # short arm minus the overlap with the long arm
    long_arm = (vert.x0, vert.y0, vert.x1, vert.y1)
    sx, sy = K["sink_x"], K["sink_y"]
    hole = (sx - 0.75, sy - 0.50, sx + 0.75, sy + 0.50)
    basin_floor = 1.05

    # carcass (dark) -------------------------------------------------------------------
    mb.box(long_arm[0], long_arm[1], 0.0, long_arm[2], long_arm[3], slab_z0, CABINET)
    mb.box(arm[0], arm[1], 0.0, arm[2], arm[3], basin_floor, CABINET)
    for r in _rects_minus_hole(arm, hole):
        if r[2] - r[0] > 1e-6 and r[3] - r[1] > 1e-6:
            mb.box(r[0], r[1], basin_floor, r[2], r[3], slab_z0, CABINET)
    # countertop (white) with the sink cut-out -----------------------------------------
    mb.box(long_arm[0], long_arm[1], slab_z0, long_arm[2], long_arm[3], top, COUNTER_TOP)
    for r in _rects_minus_hole(arm, hole):
        if r[2] - r[0] > 1e-6 and r[3] - r[1] > 1e-6:
            mb.box(r[0], r[1], slab_z0, r[2], r[3], top, COUNTER_TOP)
    mb.box(arm[0], y0 - 0.03, slab_z0, arm[2], y0, top, COUNTER_TOP)                  # front lip
    mb.box(vert.x1, vert.y0, slab_z0, vert.x1 + 0.03, y0 - 0.03, top, COUNTER_TOP)     # side lip

    _basin(mb, hole, basin_floor, top, STEEL, (0.62, 0.63, 0.65, 1))
    _gooseneck(mb, sx, hole[3] + 0.22, top, reach=0.80, rise=0.80, r=0.055)

    g, zlo, zhi, prot = 0.03, 0.10, 1.50, 0.03
    # sink cabinet: one door ---------------------------------------------------------------
    a, b = K["cabinet"]
    mb.box(a + g, y0 - prot, zlo, b - g, y0, zhi, CABINET_FRONT)
    _handle_bar_z(mb, b - 0.14, y0 - prot, zhi - 0.65, zhi - 0.15)
    # dishwasher: stainless front, dark control strip, bar handle ----------------------------
    a, b = K["dishwasher"]
    mb.box(a + 0.02, y0 - 0.04, 0.08, b - 0.02, y0, 1.50, STEEL)
    mb.box(a + 0.04, y0 - 0.047, 1.34, b - 0.04, y0 - 0.04, 1.48, (0.10, 0.10, 0.11, 1))
    _handle_bar_x(mb, a + 0.22, b - 0.22, y0 - 0.04, 1.22, out=0.12, r=0.03)

    # stove + oven on the long arm, oven door facing east into the kitchen --------------------
    ry0, ry1 = K["range_y"]
    with mb.at(vert.x1, (ry0 + ry1) / 2, 0.0, h=90):
        _stove(mb, -(ry1 - ry0) / 2, (ry1 - ry0) / 2, 0.0, top, depth=1.4)

    # three drawers stacked beside the stove --------------------------------------------------
    dy0, dy1 = K["drawers_y"]
    xf = vert.x1
    n = 3
    h = (zhi - zlo - (n - 1) * g) / n
    for k in range(n):
        z0 = zlo + k * (h + g)
        mb.box(xf, dy0 + g, z0, xf + prot, dy1 - g, z0 + h, CABINET_FRONT)
        zc, yc = z0 + h * 0.62, (dy0 + dy1) / 2
        mb.cyl_between((xf + prot + 0.11, yc - 0.28, zc), (xf + prot + 0.11, yc + 0.28, zc), 0.028, STEEL_LIGHT, 8)
        for yy in (yc - 0.24, yc + 0.24):
            mb.cyl_between((xf + prot, yy, zc), (xf + prot + 0.11, yy, zc), 0.022, STEEL_LIGHT, 6)
    return mb.build(parent)


def _stove(mb: MeshBuilder, a: float, b: float, y0: float, top: float, depth: float = 1.5) -> None:
    yf = y0 - 0.05
    depth_end = y0 + depth - 0.05
    cx = (a + b) / 2
    body_top = top + 0.012
    mb.box(a, yf, 0.0, b, depth_end, body_top, STEEL)
    mb.box(a + 0.04, yf + 0.04, body_top, b - 0.04, depth_end - 0.05, body_top + 0.02, (0.06, 0.06, 0.07, 1))   # cooktop glass
    zt = body_top + 0.02
    for dx in (-0.33, 0.33):
        for dy in (0.50, 1.10):
            mb.cylinder(cx + dx, yf + dy, zt, zt + 0.012, 0.25, (0.34, 0.34, 0.36, 1), 18)
            mb.cylinder(cx + dx, yf + dy, zt + 0.012, zt + 0.02, 0.17, (0.09, 0.09, 0.10, 1), 18)
    # front: knobs strip + oven door
    for i in range(5):
        kx = a + 0.22 + i * (b - a - 0.44) / 4
        mb.cyl_between((kx, yf, 1.40), (kx, yf - 0.10, 1.40), 0.07, (0.12, 0.12, 0.13, 1), 12)
        mb.cyl_between((kx, yf - 0.095, 1.40), (kx, yf - 0.105, 1.40), 0.085, STEEL_LIGHT, 12)
    mb.box(a + 0.06, yf - 0.03, 0.14, b - 0.06, yf, 1.10, STEEL_LIGHT)
    mb.box(a + 0.22, yf - 0.05, 0.34, b - 0.22, yf - 0.03, 0.94, (0.07, 0.07, 0.08, 1))
    _handle_bar_x(mb, a + 0.18, b - 0.18, yf - 0.03, 1.03, out=0.13, r=0.035)
    mb.box(a + 0.06, yf - 0.02, 0.0, b - 0.06, yf, 0.12, (0.60, 0.61, 0.63, 1))


def build_fridge(parent: NodePath) -> NodePath:
    w, d, h = F.FRIDGE_SIZE
    mb = MeshBuilder("fridge")
    body = (0.70, 0.72, 0.74, 1)
    panel = (0.78, 0.79, 0.81, 1)
    mb.box(-w / 2, -d / 2, 0.06, w / 2, d / 2, h, body)
    mb.box(-w / 2 + 0.05, -d / 2 + 0.05, 0.0, w / 2 - 0.05, d / 2 - 0.05, 0.06, (0.06, 0.06, 0.07, 1))
    split = 1.18
    mb.box(-w / 2 + 0.02, -d / 2 - 0.05, 0.10, w / 2 - 0.02, -d / 2, split - 0.015, panel)
    mb.box(-w / 2 + 0.02, -d / 2 - 0.05, split + 0.015, w / 2 - 0.02, -d / 2, h - 0.04, panel)
    hx = w / 2 - 0.20
    yh = -d / 2 - 0.15
    for z0, z1 in ((split + 0.30, split + 1.60), (0.22, 0.95)):                     # vertical bar handles
        mb.cyl_between((hx, yh, z0), (hx, yh, z1), 0.04, CHROME, 10)
        for z in (z0 + 0.06, z1 - 0.06):
            mb.cyl_between((hx, -d / 2 - 0.05, z), (hx, yh, z), 0.025, CHROME, 8)
    return mb.build(parent)


# =========================================================================================
# Bathroom
# =========================================================================================
def build_bathtub(parent: NodePath) -> NodePath:
    W, D, H = F.TUB_SIZE
    t = 0.16
    mb = MeshBuilder("bathtub")
    mb.box(-W / 2, -D / 2, 0.0, W / 2, D / 2, 0.30, WHITE)
    mb.box(-W / 2, -D / 2, 0.0, -W / 2 + t, D / 2, H, WHITE)
    mb.box(W / 2 - t, -D / 2, 0.0, W / 2, D / 2, H, WHITE)
    mb.box(-W / 2 + t, -D / 2, 0.0, W / 2 - t, -D / 2 + t, H, WHITE)
    mb.box(-W / 2 + t, D / 2 - t, 0.0, W / 2 - t, D / 2, H, WHITE)
    mb.box(-W / 2 + t, -D / 2 + t, 0.30, W / 2 - t, D / 2 - t, 0.34, (0.88, 0.90, 0.92, 1))
    mb.cylinder(W / 2 - 0.55, 0.0, 0.34, 0.345, 0.07, (0.25, 0.25, 0.27, 1), 12)

    # wall-mounted shower head on the SOUTH wall (same wall as the toilet), aimed down into the tub.
    # The tub's local +X end is its south end, so the wall plate sits at x = +W/2.
    xw = W / 2
    mb.cyl_between((xw + 0.02, 0.0, 3.00), (xw - 0.02, 0.0, 3.00), 0.10, CHROME, 12)
    mb.cyl_between((xw - 0.02, 0.0, 3.00), (xw - 0.50, 0.0, 3.12), 0.045, CHROME, 10)
    n = (-0.55, 0.0, -0.83)
    p0 = (xw - 0.58, 0.0, 3.10)
    mb.cyl_between(p0, (p0[0] + n[0] * 0.11, p0[1], p0[2] + n[2] * 0.11), 0.30, CHROME, 18)
    mb.cyl_between((p0[0] + n[0] * 0.108, p0[1], p0[2] + n[2] * 0.108),
                   (p0[0] + n[0] * 0.118, p0[1], p0[2] + n[2] * 0.118), 0.23, (0.30, 0.30, 0.33, 1), 18)
    return mb.build(parent)


def build_shower_curtain(parent: NodePath) -> NodePath:
    """Translucent curtain on a rod along the tub's open side, pushed to the east end."""
    W, D, H = F.TUB_SIZE
    mb = MeshBuilder("shower_curtain", tone=0.85)
    yf = -D / 2 - 0.03
    zt = 3.35
    mb.cyl_between((-W / 2, yf, zt), (W / 2, yf, zt), 0.04, CHROME, 10)               # rod
    x0 = -W / 2 + 0.05
    x1 = x0 + 0.95
    wl, amp = 0.26, 0.12
    cols = int((x1 - x0) / (wl / 8)) + 1
    grid = []
    for z in (zt - 0.05, zt - 0.75, zt - 1.45, 1.20):
        row = []
        for j in range(cols):
            x = x0 + (x1 - x0) * j / (cols - 1)
            row.append((x, yf + amp * math.sin(2 * math.pi * (x - x0) / wl), z))
        grid.append(row)
    mb.sheet(grid, colour=(0.95, 0.96, 0.98, 0.55))
    np = mb.build(parent)
    np.setTwoSided(True)
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setDepthWrite(False)
    return np


def build_toilet(parent: NodePath) -> NodePath:
    mb = MeshBuilder("toilet")
    seat = (0.93, 0.93, 0.92, 1)
    mb.cylinder(0.0, -0.05, 0.0, 0.55, 0.30, WHITE, 16)                               # pedestal
    mb.ellipsoid(0.0, -0.08, 0.62, 0.52, 0.64, 0.34, WHITE, 8, 16)                    # bowl
    mb.ellipsoid(0.0, -0.08, 0.92, 0.50, 0.62, 0.06, seat, 6, 16)                     # closed lid
    mb.box(-0.55, 0.28, 0.45, 0.55, 0.70, 1.55, WHITE)                                # tank
    mb.box(-0.58, 0.26, 1.55, 0.58, 0.72, 1.62, seat)
    mb.cylinder(0.0, 0.49, 1.62, 1.68, 0.07, CHROME, 12)                              # flush button
    return mb.build(parent)


def build_vanity(parent: NodePath) -> NodePath:
    W, D = F.VANITY_SIZE
    top = 1.62
    slab_z0 = top - 0.08
    mb = MeshBuilder("bathroom_sink")
    rect = (-W / 2, -D / 2, W / 2, D / 2)
    hole = (-0.50, -0.34, 0.50, 0.34)
    basin_floor = 1.28
    mb.box(*rect[:2], 0.0, *rect[2:], basin_floor, CABINET)
    for r in _rects_minus_hole(rect, hole):
        mb.box(r[0], r[1], basin_floor, r[2], r[3], slab_z0, CABINET)
    for r in _rects_minus_hole((rect[0] - 0.04, rect[1] - 0.04, rect[2] + 0.04, rect[3]), hole):
        mb.box(r[0], r[1], slab_z0, r[2], r[3], top, MARBLE)
    _basin(mb, hole, basin_floor, top, WHITE, (0.90, 0.91, 0.92, 1))
    _gooseneck(mb, 0.0, D / 2 - 0.16, top, reach=0.50, rise=0.38, r=0.045)
    g = 0.03
    for k in range(2):                                                               # two door fronts
        xa, xb = rect[0] + k * W / 2, rect[0] + (k + 1) * W / 2
        mb.box(xa + g, -D / 2 - 0.03, 0.10, xb - g, -D / 2, slab_z0 - 0.02, CABINET_FRONT)
        hx = xb - 0.12 - g if k == 0 else xa + 0.12 + g
        _handle_bar_z(mb, hx, -D / 2 - 0.03, 1.0, 1.45)
    return mb.build(parent)


def build_rug(parent: NodePath, size, base, trim) -> NodePath:
    w, d = size
    mb = MeshBuilder("rug")
    mb.box(-w / 2, -d / 2, 0.012, w / 2, d / 2, 0.06, base)
    mb.box(-w / 2 + 0.08, -d / 2 + 0.08, 0.06, w / 2 - 0.08, d / 2 - 0.08, 0.067, trim)
    return mb.build(parent)


# =========================================================================================
# Assemble
# =========================================================================================
def build_apartment(parent: NodePath) -> list[tuple[NodePath, Box]]:
    """Builds every prop under `parent`. Returns (node, box) pairs for tall things that should
    fade out when they hide the player from the camera."""
    root = parent.attachNewNode("furniture")
    fade: list[tuple[NodePath, Box]] = []

    # bedroom
    _place(build_bed(root), F.BED)
    _place(build_crate(root), F.CRATE)
    # living room
    _place(build_shelf(root), F.SHELF)
    _place(build_desk(root), F.DESK)
    _place(build_chair(root), F.CHAIR)
    _place(build_couch(root), F.COUCH)
    # kitchen
    build_kitchen(root)
    fr = _place(build_fridge(root), F.FRIDGE)
    w, d, h = F.FRIDGE_SIZE
    fade.append((fr, Box(F.FRIDGE.x - w / 2, F.FRIDGE.y - d / 2, F.FRIDGE.x + w / 2, F.FRIDGE.y + d / 2, 0.0, h)))
    # bathroom
    _place(build_bathtub(root), F.TUB)
    _place(build_shower_curtain(root), F.TUB)
    _place(build_toilet(root), F.TOILET)
    _place(build_vanity(root), F.VANITY)
    _place(build_rug(root, F.BATH_RUG_SIZE, (0.06, 0.06, 0.07, 1), (0.10, 0.10, 0.11, 1)), F.BATH_RUG)   # black rug
    _place(build_rug(root, F.ENTRY_MAT_SIZE, (0.20, 0.12, 0.08, 1), (0.27, 0.17, 0.11, 1)), F.ENTRY_MAT)   # dark brown mat
    # curtains (4 per room)
    for c in F.curtains():
        fade.append((build_curtain(root, c), F.curtain_fade_box(c)))
    return fade
