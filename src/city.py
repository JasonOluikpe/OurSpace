from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from panda3d.core import (
    Fog,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    PNMImage,
    SamplerState,
    Texture,
    Vec4,
)

from src import furniture, layout
from src.meshes import MeshBuilder
from src.traffic import Traffic


# --------------------------------------------------------------------------------------
# Downtown Toronto around the apartment (Bay St / St Joseph St, Clover Hill Park).
#
# The city is authored in REAL metres in a frame whose origin is the NE corner of our tower's
# north facade (+X east, +Y north, Z up from street level). `self.root` maps that frame into
# game space: S = 2 matches the 2x furniture scale, and the street sits DROP metres below our floor.
# Our tower is cut off at our floor ("the ceiling cut in half"): nothing above it is rendered.
#
# Only what is near the player exists: ground chunks, buildings and trees are created on demand
# within DRAW_R and removed again beyond KEEP_R; traffic only simulates cars near the focus.
# --------------------------------------------------------------------------------------
S = 2.0
FLOOR_H = 75.0                                    # 25 storeys at 3 m (real m above the street)
DROP = FLOOR_H * S                                # game metres from our floor down to the street
X0 = furniture.EAST_IN + 3.0                      # game x of the tower's NE facade corner
Y0 = layout.W(layout.ROOM_R, layout.BALC_T)[1]    # game y of the balcony edge = north facade
LOBBY_H = 8.0                                     # glass base of the tower (real m)

CH = 32.0                                         # chunk size (real m)
DRAW_R = 200.0                                    # real m
KEEP_R = 280.0
BUILDS_PER_FRAME = 2

BG = (0.07, 0.09, 0.15, 1.0)


def G(xr: float, yr: float) -> tuple[float, float]:
    return X0 + xr * S, Y0 + yr * S


def R(xg: float, yg: float) -> tuple[float, float]:
    return (xg - X0) / S, (yg - Y0) / S


# ------------------------------------------------------------------------------ ground plan (real m)
BAY_ROAD = (4.0, 30.0)
SJ_ROAD = (8.0, 20.0)
EW_STEP, NS_STEP = 120.0, 180.0                   # spacing of the extra cross streets
EXTRA_HALF = 6.0

PARK = (-84.0, 24.0, 0.0, 120.0)                  # Clover Hill Park
PARK_PATH = [(-60, 120), (-55, 100), (-44, 72), (-30, 52), (-12, 32), (-3, 24)]
TOWER = (-30.0, -97.0, 0.0, 0.0)                  # our tower footprint incl. podium

COL = {
    "ground": (0.20, 0.21, 0.22), "asphalt": (0.19, 0.20, 0.22), "sidewalk": (0.50, 0.50, 0.49),
    "plaza": (0.44, 0.43, 0.42), "lawn": (0.19, 0.38, 0.18), "lawn2": (0.24, 0.45, 0.20),
    "path": (0.56, 0.54, 0.48), "white": (0.85, 0.85, 0.82), "yellow": (0.85, 0.68, 0.10),
    "pool": (0.22, 0.60, 0.74), "greenroof": (0.30, 0.46, 0.22),
}


def _big(v: float = 700.0) -> float:
    return v


def static_features() -> list[tuple]:
    """Large flat rectangles: (x0, y0, x1, y1, layer, colour_key)."""
    b = _big()
    f: list[tuple] = []
    # extra cross streets first (they sit under Bay / St Joseph markings but over sidewalks)
    for k in range(-6, 7):
        if k == 0:
            continue
        yc = 14.0 + EW_STEP * k
        f.append((-b, yc - EXTRA_HALF - 4, b, yc + EXTRA_HALF + 4, 0.06, "sidewalk"))
        f.append((-b, yc - EXTRA_HALF, b, yc + EXTRA_HALF, 0.07, "asphalt"))
    for m in range(-5, 6):
        if m == 0:
            continue
        xc = 17.0 + NS_STEP * m
        f.append((xc - EXTRA_HALF - 4, -b, xc + EXTRA_HALF + 4, b, 0.06, "sidewalk"))
        f.append((xc - EXTRA_HALF, -b, xc + EXTRA_HALF, b, 0.07, "asphalt"))
    # Bay St
    f.append((BAY_ROAD[0], -b, BAY_ROAD[1], b, 0.02, "asphalt"))
    f.append((0.0, -b, 4.0, SJ_ROAD[0], 0.06, "sidewalk"))
    f.append((0.0, SJ_ROAD[1], 4.0, b, 0.06, "sidewalk"))
    f.append((30.0, -b, 34.0, SJ_ROAD[0], 0.06, "sidewalk"))
    f.append((30.0, SJ_ROAD[1], 34.0, b, 0.06, "sidewalk"))
    # St Joseph St
    f.append((-b, SJ_ROAD[0], BAY_ROAD[0], SJ_ROAD[1], 0.03, "asphalt"))
    f.append((BAY_ROAD[1], SJ_ROAD[0], b, SJ_ROAD[1], 0.03, "asphalt"))
    f.append((-b, 4.0, 0.0, 8.0, 0.06, "sidewalk"))
    f.append((34.0, 4.0, b, 8.0, 0.06, "sidewalk"))
    f.append((-b, 20.0, 0.0, 24.0, 0.06, "sidewalk"))
    f.append((34.0, 20.0, b, 24.0, 0.06, "sidewalk"))
    # plaza in front of our tower, park lawn
    f.append((TOWER[0], 0.0, 0.0, 4.0, 0.05, "plaza"))
    f.append((PARK[0], PARK[1], PARK[2], PARK[3], 0.05, "lawn"))
    f.append((-84.0, 30.0, -62.0, 72.0, 0.055, "lawn2"))
    f.append((-40.0, 90.0, -8.0, 118.0, 0.055, "lawn2"))
    return f


def _band_hit(x0, y0, x1, y1, margin=0.0) -> bool:
    """Does a rectangle touch any street (authored or extra)?"""
    if x1 > -1 - margin and x0 < 35 + margin:
        return True                                           # Bay St corridor
    if y1 > 3 - margin and y0 < 25 + margin:
        return True                                           # St Joseph corridor
    for k in range(-6, 7):
        yc = 14.0 + EW_STEP * k
        if k and y1 > yc - 12 - margin and y0 < yc + 12 + margin:
            return True
    for m in range(-5, 6):
        xc = 17.0 + NS_STEP * m
        if m and x1 > xc - 12 - margin and x0 < xc + 12 + margin:
            return True
    return False


# ------------------------------------------------------------------------------ buildings
@dataclass
class Building:
    boxes: list                                   # (x0, y0, x1, y1, height above street)
    style: str
    seed: int = 0
    roof: str = "flat"                            # or "gable"
    decals: list = field(default_factory=list)    # (x0, y0, x1, y1, colour_key) painted on the roof

    def bbox(self):
        return (min(b[0] for b in self.boxes), min(b[1] for b in self.boxes),
                max(b[2] for b in self.boxes), max(b[3] for b in self.boxes))


def authored_buildings() -> list[Building]:
    return [
        # our tower's low podium to the south (pool deck), below our floor
        Building([(-12.6, -40.1, -0.4, 0.0, 12.0)], "concrete", 1,
                 decals=[(-11.0, -36.0, -5.0, -26.0, "pool")]),
        # east of Bay St: tan balcony towers with stepped, chamfered massing
        Building([(34, -45, 64, 4, 32.0), (64, -30, 80, -5, 26.0), (34, -45, 50, -62, 22.0)], "tan_balcony", 2),
        # 7-Eleven corner: low brick podium (3 storeys) with a glass corner, then a taller brown brick tower above it
        Building([(34, 24, 64, 50, 9.0), (52, 24, 64, 50, 9.0), (34, 42, 64, 50, 9.0),
                 (34, 24, 52, 42, 30.0)], "brick_low", 3),
        Building([(70, 24, 110, 40, 24.0)], "concrete", 4),
        Building([(84, -60, 130, -8, 30.0)], "tan_balcony", 5),
        # west: library / college buildings (brick, low)
        Building([(-125, -60, -72, -20, 10.0)], "brick_low", 6),
        Building([(-64, -48, -34, -8, 12.0)], "brick_low", 7),
        Building([(-100, -112, -50, -72, 8.0)], "brick_low", 8, roof="gable"),
        # north-west: St Michael's campus houses around the park
        Building([(-150, 40, -100, 64, 9.0)], "brick_low", 9, roof="gable"),
        Building([(-140, 68, -118, 84, 8.0)], "brick_low", 10, roof="gable"),
        Building([(-112, 70, -92, 86, 8.0)], "brick_low", 11, roof="gable"),
        Building([(-120, 22, -100, 36, 8.0)], "brick_low", 12, roof="gable"),
    ]


STYLES = ["tan_balcony", "glass_tower", "brick_low", "concrete", "slab"]


def filler_buildings(ci: int, cj: int, taken: list) -> list[Building]:
    """Deterministic anonymous downtown blocks for chunk (ci, cj), keeping clear of streets / park / authored."""
    rng = random.Random(ci * 7919 + cj * 104729 + 17)
    out: list[Building] = []
    x_base, y_base = ci * CH, cj * CH
    for _ in range(rng.randint(1, 3)):
        w, d = rng.uniform(18, 34), rng.uniform(18, 34)
        x0 = x_base + rng.uniform(0, max(1.0, CH - w * 0.5))
        y0 = y_base + rng.uniform(0, max(1.0, CH - d * 0.5))
        rect = (x0, y0, x0 + w, y0 + d)
        if _band_hit(*rect, margin=6.0):
            continue
        if any(not (rect[2] < t[0] or rect[0] > t[2] or rect[3] < t[1] or rect[1] > t[3]) for t in taken):
            continue
        taken.append(rect)
        h = rng.choice([12, 16, 20, 24, 28, 32, 34])
        style = rng.choice(STYLES)
        out.append(Building([(*rect, float(h))], style, rng.randint(0, 9999),
                            roof="gable" if style == "brick_low" and h <= 12 and rng.random() < 0.5 else "flat"))
    return out


# ------------------------------------------------------------------------------ textures
_TEX: dict = {}
_TILE = {"tan_balcony": (8.8, 12.0), "glass_tower": (8.0, 12.0), "brick_low": (9.0, 9.0),
         "concrete": (8.0, 9.0), "slab": (8.0, 12.0)}


def _fill(img, x0, y0, x1, y1, col):
    for y in range(max(0, y0), min(img.getYSize(), y1)):
        for x in range(max(0, x0), min(img.getXSize(), x1)):
            img.setXel(x, y, *col)


def facade_texture(style: str, variant: int) -> Texture:
    key = (style, variant % 3)
    if key in _TEX:
        return _TEX[key]
    rng = random.Random(hash(style) % 1000 + variant * 31)
    N, cell = 128, 32
    img = PNMImage(N, N, 3)
    lit = (0.98, 0.80, 0.46)
    dark = (0.10, 0.13, 0.19)

    def win(x0, y0, x1, y1, p=0.3):
        _fill(img, x0, y0, x1, y1, lit if rng.random() < p else dark)

    if style == "tan_balcony":
        _fill(img, 0, 0, N, N, (0.60, 0.44, 0.36))
        for r in range(4):
            for c in range(4):
                x, y = c * cell, r * cell
                _fill(img, x + 3, y + 3, x + 29, y + 23, (0.35, 0.27, 0.22))      # frame
                win(x + 5, y + 5, x + 27, y + 21)
                _fill(img, x, y + 25, x + cell, y + 31, (0.82, 0.79, 0.72))       # balcony slab
                _fill(img, x, y + 31, x + cell, y + 32, (0.30, 0.25, 0.22))
                _fill(img, x + 2, y + 23, x + 30, y + 25, (0.25, 0.25, 0.27))     # railing
    elif style == "glass_tower":
        _fill(img, 0, 0, N, N, (0.30, 0.35, 0.42))
        for r in range(4):
            for c in range(4):
                x, y = c * cell, r * cell
                _fill(img, x + 1, y + 1, x + 31, y + 23, (0.12, 0.20, 0.30))
                win(x + 2, y + 2, x + 30, y + 22, 0.22)
                _fill(img, x + 1, y + 23, x + 31, y + 31, (0.07, 0.09, 0.12))     # spandrel
    elif style == "brick_low":
        _fill(img, 0, 0, N, N, (0.50, 0.27, 0.21))
        for y in range(0, N, 4):
            _fill(img, 0, y, N, y + 1, (0.36, 0.19, 0.15))
        for r in range(4):
            for c in range(4):
                x, y = c * cell, r * cell
                _fill(img, x + 7, y + 6, x + 25, y + 26, (0.86, 0.85, 0.80))      # stone frame
                win(x + 9, y + 8, x + 23, y + 24, 0.25)
                _fill(img, x + 6, y + 26, x + 26, y + 28, (0.78, 0.76, 0.70))     # sill
    elif style == "slab":
        _fill(img, 0, 0, N, N, (0.82, 0.82, 0.83))
        for r in range(4):
            for c in range(4):
                x, y = c * cell, r * cell
                _fill(img, x + 7, y + 6, x + 25, y + 26, (0.16, 0.18, 0.22))     # window
                win(x + 9, y + 8, x + 23, y + 24, 0.25)
                _fill(img, x + 5, y + 26, x + 27, y + 29, (0.90, 0.90, 0.91))     # sill
    else:   # concrete
        _fill(img, 0, 0, N, N, (0.40, 0.40, 0.42))
        for r in range(4):
            y = r * cell
            _fill(img, 0, y + 9, N, y + 23, (0.12, 0.16, 0.22))
            for c in range(8):
                win(c * 16 + 1, y + 10, c * 16 + 15, y + 22, 0.2)
            _fill(img, 0, y + 23, N, y + 25, (0.62, 0.62, 0.60))
    # lighting in the scene brightens albedo; keep facades from blowing out
    for y in range(N):
        for x in range(N):
            r, g, b = img.getXel(x, y)
            img.setXel(x, y, r * 0.78, g * 0.78, b * 0.78)
    tex = Texture(f"facade-{style}-{variant % 3}")
    tex.load(img)
    tex.setWrapU(SamplerState.WM_repeat)
    tex.setWrapV(SamplerState.WM_repeat)
    tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setAnisotropicDegree(4)
    _TEX[key] = tex
    return tex


class FacadeBuilder(MeshBuilder):
    """MeshBuilder that also writes texture coordinates (for repeating window textures)."""

    def __init__(self, name: str) -> None:
        super().__init__(name, tone=1.0)
        self._uv: list[tuple[float, float]] = []

    def _vert(self, p, n, col) -> int:
        i = super()._vert(p, n, col)
        self._uv.append((0.0, 0.0))
        return i

    def wall(self, p0, p1, z0, z1, tw, th) -> None:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        L = math.hypot(dx, dy)
        n = (dy / L, -dx / L, 0.0)
        white = (1.0, 1.0, 1.0, 1.0)
        base = len(self._v)
        for (p, z, u, v) in ((p0, z0, 0.0, 0.0), (p1, z0, L / tw, 0.0),
                             (p1, z1, L / tw, (z1 - z0) / th), (p0, z1, 0.0, (z1 - z0) / th)):
            i = self._vert((p[0], p[1], z), n, white)
            self._uv[i] = (u, v)
        self._tris.append((base, base + 1, base + 2))
        self._tris.append((base, base + 2, base + 3))

    def build(self, parent: NodePath) -> NodePath:
        fmt = GeomVertexFormat.getV3n3c4t2()
        vdata = GeomVertexData(self.name, fmt, Geom.UHStatic)
        vdata.setNumRows(len(self._v))
        vw, nw = GeomVertexWriter(vdata, "vertex"), GeomVertexWriter(vdata, "normal")
        cw, tw = GeomVertexWriter(vdata, "color"), GeomVertexWriter(vdata, "texcoord")
        for v, n, c, uv in zip(self._v, self._n, self._c, self._uv):
            vw.addData3(*v)
            nw.addData3(*n)
            cw.addData4(*c)
            tw.addData2(*uv)
        prim = GeomTriangles(Geom.UHStatic)
        for a, b, c in self._tris:
            prim.addVertices(a, b, c)
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode(self.name)
        node.addGeom(geom)
        np = NodePath(node)
        np.reparentTo(parent)
        return np


def _finish(mb: MeshBuilder, parent: NodePath):
    return mb.build(parent) if mb._tris else None


# ------------------------------------------------------------------------------ building meshes
ROOF = (0.62, 0.62, 0.60)
ROOF_DARK = (0.42, 0.42, 0.44)
SLATE = (0.26, 0.28, 0.35)
TERRACOTTA = (0.52, 0.27, 0.22)


def build_building(b: Building, parent: NodePath) -> NodePath:
    root = parent.attachNewNode("building")
    rng = random.Random(b.seed)
    tw, th = _TILE[b.style]
    fb = FacadeBuilder("facade")
    rf = MeshBuilder("roof", tone=0.72)
    for (x0, y0, x1, y1, h) in b.boxes:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        for i in range(4):
            fb.wall(pts[i], pts[(i + 1) % 4], 0.0, h, tw, th)
        if b.roof == "gable":
            _gable(rf, x0, y0, x1, y1, h, SLATE if b.seed % 2 else TERRACOTTA)
            continue
        rf.box(x0, y0, h - 0.05, x1, y1, h, ROOF)                                   # roof slab
        e, ph = 0.45, 0.55                                                           # parapet
        for bx in ((x0, y0, x1, y0 + e), (x0, y1 - e, x1, y1), (x0, y0, x0 + e, y1), (x1 - e, y0, x1, y1)):
            rf.box(bx[0], bx[1], h, bx[2], bx[3], h + ph, (0.74, 0.74, 0.72))
        area = (x1 - x0) * (y1 - y0)
        for _ in range(int(area / 160) + 1):                                         # rooftop units
            w, d, hh = rng.uniform(1.6, 3.6), rng.uniform(1.6, 3.0), rng.uniform(0.8, 2.2)
            if x1 - x0 < w + 2 or y1 - y0 < d + 2:
                continue
            ux, uy = rng.uniform(x0 + 1, x1 - w - 1), rng.uniform(y0 + 1, y1 - d - 1)
            rf.box(ux, uy, h, ux + w, uy + d, h + hh, rng.choice([(0.70, 0.70, 0.72), (0.50, 0.52, 0.54), (0.62, 0.64, 0.60)]))
        if area > 500:                                                               # stair / elevator penthouse
            ux, uy = x0 + (x1 - x0) * rng.uniform(0.2, 0.6), y0 + (y1 - y0) * rng.uniform(0.2, 0.6)
            rf.box(ux, uy, h, ux + 5.0, uy + 4.0, h + 3.2, (0.58, 0.58, 0.60))
    for (x0, y0, x1, y1, ck) in b.decals:
        top = b.boxes[0][4]
        rf.quad((x0, y0, top + 0.12), (x1, y0, top + 0.12), (x1, y1, top + 0.12), (x0, y1, top + 0.12), COL[ck], (0, 0, 1))
    n = fb.build(root)
    n.setTexture(facade_texture(b.style, b.seed))
    _finish(rf, root)
    return root


def _gable(mb: MeshBuilder, x0, y0, x1, y1, h, col) -> None:
    w, d = x1 - x0, y1 - y0
    rise = min(w, d) * 0.32
    if w >= d:      # ridge along X
        ym = (y0 + y1) / 2
        mb.quad((x0 - .4, y0 - .4, h), (x1 + .4, y0 - .4, h), (x1 + .4, ym, h + rise), (x0 - .4, ym, h + rise), col)
        mb.quad((x0 - .4, y1 + .4, h), (x0 - .4, ym, h + rise), (x1 + .4, ym, h + rise), (x1 + .4, y1 + .4, h), col)
        mb.quad((x0, y0, h), (x0, ym, h + rise), (x0, y1, h), (x0, y1, h), (0.50, 0.27, 0.21), (-1, 0, 0))
        mb.quad((x1, y0, h), (x1, y1, h), (x1, ym, h + rise), (x1, ym, h + rise), (0.50, 0.27, 0.21), (1, 0, 0))
    else:           # ridge along Y
        xm = (x0 + x1) / 2
        mb.quad((x0 - .4, y0 - .4, h), (xm, y0 - .4, h + rise), (xm, y1 + .4, h + rise), (x0 - .4, y1 + .4, h), col)
        mb.quad((x1 + .4, y0 - .4, h), (x1 + .4, y1 + .4, h), (xm, y1 + .4, h + rise), (xm, y0 - .4, h + rise), col)
        mb.quad((x0, y0, h), (x1, y0, h), (xm, y0, h + rise), (xm, y0, h + rise), (0.50, 0.27, 0.21), (0, -1, 0))
        mb.quad((x0, y1, h), (xm, y1, h + rise), (x1, y1, h), (x1, y1, h), (0.50, 0.27, 0.21), (0, 1, 0))


# ------------------------------------------------------------------------------ trees
def _tree(mb: MeshBuilder, x, y, r, rng) -> None:
    th = r * 0.9
    mb.cylinder(x, y, 0.0, th, 0.28 + r * 0.02, (0.30, 0.22, 0.16), 7)
    greens = [(0.13, 0.30, 0.14), (0.17, 0.36, 0.16), (0.11, 0.26, 0.13), (0.22, 0.40, 0.18)]
    for k in range(3):
        a = rng.uniform(0, 6.28)
        ox, oy = math.cos(a) * r * 0.35 * (k > 0), math.sin(a) * r * 0.35 * (k > 0)
        mb.ellipsoid(x + ox, y + oy, th + r * (0.55 + 0.2 * k), r * (1.0 - 0.12 * k), r * (1.0 - 0.12 * k),
                     r * 0.8, rng.choice(greens), 5, 8)


def park_trees() -> list[tuple[float, float, float, int]]:
    rng = random.Random(1020)                                  # "1020", the park's address label
    out: list[tuple[float, float, float, int]] = []
    tries = 0
    while len(out) < 120 and tries < 4000:
        tries += 1
        x, y = rng.uniform(PARK[0] + 4, PARK[2] - 3), rng.uniform(PARK[1] + 4, PARK[3] - 4)
        if -90 < x < -62 and 30 < y < 72:
            continue                                           # open lawn at the west edge
        if any(math.hypot(x - px, y - py) < 8.0 for px, py, _, _ in out):
            continue
        if _near_path(x, y, 5.0):
            continue
        out.append((x, y, rng.uniform(4.5, 7.5), rng.randint(0, 99)))
    return out


def _near_path(x, y, d) -> bool:
    for (ax, ay), (bx, by) in zip(PARK_PATH, PARK_PATH[1:]):
        vx, vy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / (vx * vx + vy * vy)))
        if math.hypot(x - (ax + vx * t), y - (ay + vy * t)) < d:
            return True
    return False


def street_trees() -> list[tuple[float, float, float, int]]:
    out = []
    for k in range(-14, 15):
        y = k * 13.0 + 3
        for x in (2.0, 32.0):
            if SJ_ROAD[0] - 3 < y < SJ_ROAD[1] + 3:
                continue
            out.append((x, y, 2.6, k + 7))
    for k in range(-14, 12):
        x = k * 12.0 + 6
        if 0 < x < 34:
            continue
        out.append((x, 22.0, 2.8, k))
    return out


# ------------------------------------------------------------------------------ ground chunks
def _quad(mb, x0, y0, x1, y1, z, col):
    mb.quad((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), col, (0, 0, 1))


def build_ground_chunk(ci: int, cj: int, feats: list, trees: list, parent: NodePath) -> NodePath:
    cx0, cy0, cx1, cy1 = ci * CH, cj * CH, (ci + 1) * CH, (cj + 1) * CH
    root = parent.attachNewNode(f"chunk-{ci}-{cj}")
    mb = MeshBuilder("ground", tone=0.62)
    _quad(mb, cx0, cy0, cx1, cy1, 0.0, COL["ground"])
    for (x0, y0, x1, y1, z, ck) in feats:
        a, b, c, d = max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)
        if c > a and d > b:
            _quad(mb, a, b, c, d, z, COL[ck])

    def paint(x0, y0, x1, y1, z, ck):
        a, b, c, d = max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)
        if c > a and d > b:
            _quad(mb, a, b, c, d, z, COL[ck])

    # Bay St markings: lane dividers (dashed), double yellow centre, crosswalks around the intersection
    def in_cross(y):
        for k in range(-6, 7):
            if k and abs(y - (14.0 + EW_STEP * k)) < 13.0:
                return True
        return False

    y = math.floor(cy0 / 9.0) * 9.0
    while y < cy1:
        if not (3.0 < y < 24.0) and not in_cross(y):
            for x in (10.25, 23.75):
                paint(x - 0.1, y, x + 0.1, y + 3.0, 0.04, "white")
        y += 9.0
    for (ya, yb) in ((-700.0, 3.0), (24.0, 700.0)):
        paint(16.75, ya, 16.95, yb, 0.04, "yellow")
        paint(17.15, ya, 17.35, yb, 0.04, "yellow")
    paint(-700.0, 13.8, 0.2, 14.0, 0.04, "yellow")
    paint(-700.0, 14.2, 0.2, 14.4, 0.04, "yellow")
    paint(33.8, 13.8, 700.0, 14.0, 0.04, "yellow")
    paint(33.8, 14.2, 700.0, 14.4, 0.04, "yellow")
    for x in [4.8 + 1.2 * i for i in range(21)]:                                      # crosswalks over Bay St
        paint(x, 5.2, x + 0.6, 7.8, 0.04, "white")
        paint(x, 20.2, x + 0.6, 22.8, 0.04, "white")
    for yy in [8.6 + 1.2 * i for i in range(9)]:                                      # crosswalks over St Joseph
        paint(0.6, yy, 3.4, yy + 0.6, 0.04, "white")
        paint(30.6, yy, 33.4, yy + 0.6, 0.04, "white")

    # park path
    for (ax, ay), (bx, by) in zip(PARK_PATH, PARK_PATH[1:]):
        if max(ax, bx) + 3 < cx0 or min(ax, bx) - 3 > cx1 or max(ay, by) + 3 < cy0 or min(ay, by) - 3 > cy1:
            continue
        vx, vy = bx - ax, by - ay
        L = math.hypot(vx, vy)
        nx, ny = -vy / L * 1.7, vx / L * 1.7
        mb.quad((ax + nx, ay + ny, 0.08), (bx + nx, by + ny, 0.08), (bx - nx, by - ny, 0.08), (ax - nx, ay - ny, 0.08),
                COL["path"], (0, 0, 1))
    _finish(mb, root)

    tb = MeshBuilder("trees", tone=0.78)
    for (x, y, r, sd) in trees:
        if cx0 <= x < cx1 and cy0 <= y < cy1:
            _tree(tb, x, y, r, random.Random(sd))
    _finish(tb, root)
    root.flattenStrong()
    return root


# ------------------------------------------------------------------------------ our tower (cut-away)
def tower_box() -> tuple[float, float, float, float]:
    """Our tower's footprint in city (real-m) coords: the apartment ONLY, so the unit is the sole
    floor at the top. The entrance landing is a cantilevered balcony, not part of the building."""
    floor = layout.floor_box()
    balcony = layout.balcony_box()
    x0, y0 = R(floor.x0, floor.y0)
    x1, y1 = R(floor.x1, balcony.y1)
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def podium_box() -> tuple[float, float, float, float]:
    """Low pool-deck pod the tower rises out of, attached to its south face."""
    x0, y0, x1, y1 = tower_box()
    return x0 - 2.0, y0 - 32.0, x1 + 1.0, y1


def build_tower(parent: NodePath) -> NodePath:
    """Our tower: one apartment per floor, sliced open at our floor like the ceiling was removed."""
    root = parent.attachNewNode("our-tower")
    x0, y0, x1, y1 = tower_box()
    top = FLOOR_H - 0.05                                         # slab top flush with apartment floor (no gap)
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    # glass lobby at street level, then the light slab shaft above it
    bb = FacadeBuilder("tower-base")
    for i in range(4):
        bb.wall(pts[i], pts[(i + 1) % 4], 0.0, LOBBY_H, 8.0, LOBBY_H)
    bb.build(root).setTexture(facade_texture("glass_tower", 0))

    fb = FacadeBuilder("tower-facade")
    for i in range(4):
        fb.wall(pts[i], pts[(i + 1) % 4], LOBBY_H, top, 8.0, 12.0)
    fb.build(root).setTexture(facade_texture("slab", 0))

    return root


# ------------------------------------------------------------------------------ the city
class City:
    def __init__(self, render: NodePath) -> None:
        self.root = render.attachNewNode("city")
        self.root.setPos(X0, Y0, -DROP)
        self.root.setScale(S)

        fog = Fog("city-haze")
        fog.setColor(*BG[:3])
        fog.setLinearRange(150.0, 1000.0)
        render.setFog(fog)

        self.static = static_features()
        self.trees = park_trees() + street_trees()
        self.chunks: dict[tuple[int, int], NodePath] = {}
        self.buildings: dict[int, tuple[Building, NodePath | None]] = {}
        self._authored = authored_buildings()
        self._filler_done: set[tuple[int, int]] = set()
        tx0, ty0, tx1, ty1 = tower_box()
        px0, py0, px1, py1 = podium_box()
        self._taken = [(min(tx0, px0) - 3.0, min(ty0, py0) - 3.0,
                        max(tx1, px1) + 3.0, max(ty1, py1) + 3.0),
                       (PARK[0] - 2, PARK[1] - 2, PARK[2] + 2, PARK[3] + 2)]
        for b in self._authored:
            x0, y0, x1, y1 = b.bbox()
            self._taken.append((x0 - 3, y0 - 3, x1 + 3, y1 + 3))
        self._all: list[Building] = list(self._authored)

        build_tower(self.root)
        self.traffic = Traffic(self.root)
        self._focus = (0.0, 0.0)
        self.update(0.0, X0 - 4.0, Y0 - 16.0, immediate=True)

    # -------------------------------------------------------------------------- streaming
    def update(self, dt: float, fx: float, fy: float, immediate: bool = False) -> None:
        rx, ry = R(fx, fy)
        self._focus = (rx, ry)
        ci0, ci1 = int(math.floor((rx - DRAW_R) / CH)), int(math.floor((rx + DRAW_R) / CH))
        cj0, cj1 = int(math.floor((ry - DRAW_R) / CH)), int(math.floor((ry + DRAW_R) / CH))

        wanted = []
        for ci in range(ci0, ci1 + 1):
            for cj in range(cj0, cj1 + 1):
                cx, cy = (ci + 0.5) * CH, (cj + 0.5) * CH
                d = math.hypot(cx - rx, cy - ry)
                if d < DRAW_R + CH * 0.7:
                    wanted.append((d, ci, cj))
                    if (ci, cj) not in self._filler_done:
                        self._filler_done.add((ci, cj))
                        self._all.extend(filler_buildings(ci, cj, self._taken))
        wanted.sort()

        budget = 10 ** 6 if immediate else BUILDS_PER_FRAME
        for d, ci, cj in wanted:
            if budget <= 0:
                break
            if (ci, cj) not in self.chunks:
                self.chunks[(ci, cj)] = build_ground_chunk(ci, cj, self.static, self.trees, self.root)
                budget -= 1
        for key in [k for k in self.chunks if math.hypot((k[0] + 0.5) * CH - rx, (k[1] + 0.5) * CH - ry) > KEEP_R]:
            self.chunks.pop(key).removeNode()

        for i, b in enumerate(self._all):
            x0, y0, x1, y1 = b.bbox()
            dx = max(x0 - rx, 0.0, rx - x1)
            dy = max(y0 - ry, 0.0, ry - y1)
            dist = math.hypot(dx, dy)
            node = self.buildings.get(i, (b, None))[1]
            if dist < DRAW_R and node is None and budget > 0:
                self.buildings[i] = (b, build_building(b, self.root))
                budget -= 1
            elif dist > KEEP_R and node is not None:
                node.removeNode()
                self.buildings[i] = (b, None)

        if not immediate:
            self.traffic.update(dt, rx, ry)
        else:
            self.traffic.update(0.0, rx, ry)
