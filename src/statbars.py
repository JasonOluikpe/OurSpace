from __future__ import annotations

import math

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexRewriter,
    GeomVertexWriter,
    NodePath,
    TransparencyAttrib,
)


# ---------------------------------------------------------------- layout (aspect2d units: screen height = 2.0)
ICON_CX = 0.115          # icon centre, measured from the bottom-left corner of the screen
ICON_SIZE = 0.095
BAR_X0 = 0.135           # left edge of the bar's inner track
BAR_W = 0.58
BAR_H = 0.040
OUTLINE = 0.008
SLANT = 0.75             # sideways lean of the bar ends (x shift per unit of height)
BAND_FRACTION = 0.30     # darker strip along the top of the fill
HP_Z = 0.205
STAMINA_Z = 0.085
SMOOTHING = 10.0         # how quickly the displayed value follows the real one

COL_OUTLINE = (0.11, 0.10, 0.10, 1.0)
COL_TRACK = (0.22, 0.22, 0.23, 1.0)
COL_SHADOW = (0.0, 0.0, 0.0, 0.38)


# ---------------------------------------------------------------- polygon helpers
def _cross(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _in_tri(p, a, b, c) -> bool:
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    neg = d1 < -1e-12 or d2 < -1e-12 or d3 < -1e-12
    pos = d1 > 1e-12 or d2 > 1e-12 or d3 > 1e-12
    return not (neg and pos)


# Ear-clipping triangulation for simple (possibly concave) polygons like the bolt.
def triangulate(pts: list[tuple[float, float]]):
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    if area < 0:
        pts = pts[::-1]
    idx = list(range(len(pts)))
    tris = []
    while len(idx) > 3:
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if _cross(a, b, c) <= 1e-12:
                continue
            if any(_in_tri(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return pts, tris


def _heart_points(n: int = 40) -> list[tuple[float, float]]:
    out = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        x = 16.0 * math.sin(t) ** 3
        y = 13.0 * math.cos(t) - 5.0 * math.cos(2 * t) - 2.0 * math.cos(3 * t) - math.cos(4 * t)
        out.append((x / 32.0 + 0.5, (y + 17.0) / 29.0))
    return out


BOLT_POINTS = [(0.62, 1.0), (0.12, 0.42), (0.42, 0.42), (0.30, 0.0), (0.88, 0.58), (0.56, 0.58)]


def _make_geom(name: str, verts, tris, colour, parent: NodePath):
    vdata = GeomVertexData(name, GeomVertexFormat.getV3c4(), Geom.UHDynamic)
    vw = GeomVertexWriter(vdata, "vertex")
    cw = GeomVertexWriter(vdata, "color")
    for x, z in verts:
        vw.addData3(x, 0.0, z)
        cw.addData4(*colour)
    prim = GeomTriangles(Geom.UHStatic)
    for a, b, c in tris:
        prim.addVertices(a, b, c)
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = parent.attachNewNode(node)
    np.setTwoSided(True)
    if colour[3] < 1.0:
        np.setTransparency(TransparencyAttrib.MAlpha)
    return np, vdata


def _set_verts(vdata, verts) -> None:
    rw = GeomVertexRewriter(vdata, "vertex")
    for i, (x, z) in enumerate(verts):
        rw.setRow(i)
        rw.setData3(x, 0.0, z)


class _Icon:
    """Heart / bolt with a drop shadow and a dark outline."""

    def __init__(self, parent, name, unit_pts, cx, cz, size, colour, outline_colour) -> None:
        self.pts, self.tris = triangulate(unit_pts)

        def place(scale, dx=0.0, dz=0.0):
            return [(cx + dx + (x - 0.5) * size * scale, cz + dz + (z - 0.5) * size * scale)
                    for x, z in self.pts]

        _make_geom(f"{name}-shadow", place(1.22, 0.007, -0.014), self.tris, COL_SHADOW, parent)
        _make_geom(f"{name}-outline", place(1.22), self.tris, outline_colour, parent)
        self.fill, _ = _make_geom(f"{name}-fill", place(1.0), self.tris, colour, parent)


class _Bar:
    def __init__(self, parent, name, zc, unit_pts, fill, band, icon_fill, icon_outline) -> None:
        self.zc = zc
        self.zb, self.zt = zc - BAR_H / 2, zc + BAR_H / 2
        self.shown = 1.0
        root = parent.attachNewNode(name)

        quad = [(0, 1, 2), (0, 2, 3)]
        o = OUTLINE
        _make_geom(f"{name}-shadow", self._pts(BAR_X0 - o + 0.006, BAR_X0 + BAR_W + o + 0.006,
                                               self.zb - o - 0.011, self.zt + o - 0.011), quad, COL_SHADOW, root)
        _make_geom(f"{name}-outline", self._pts(BAR_X0 - o, BAR_X0 + BAR_W + o, self.zb - o, self.zt + o),
                   quad, COL_OUTLINE, root)
        _make_geom(f"{name}-track", self._pts(BAR_X0, BAR_X0 + BAR_W, self.zb, self.zt), quad, COL_TRACK, root)

        self.fill, self._fill_data = _make_geom(f"{name}-fill", self._pts(BAR_X0, BAR_X0 + BAR_W, self.zb, self.zt),
                                                quad, fill, root)
        self.band, self._band_data = _make_geom(f"{name}-band", self._pts(BAR_X0, BAR_X0 + BAR_W, self.zb, self.zt),
                                                quad, band, root)
        self.icon = _Icon(root, name, unit_pts, ICON_CX, zc, ICON_SIZE, icon_fill, icon_outline)

    def _pts(self, xl, xr, zb, zt):
        k, zc = SLANT, self.zc
        return [(xl + k * (zb - zc), zb), (xr + k * (zb - zc), zb),
                (xr + k * (zt - zc), zt), (xl + k * (zt - zc), zt)]

    def update(self, dt: float, fraction: float, tint=(1.0, 1.0, 1.0)) -> None:
        fraction = max(0.0, min(1.0, fraction))
        self.shown += (fraction - self.shown) * min(1.0, dt * SMOOTHING)
        if abs(self.shown - fraction) < 0.001:
            self.shown = fraction
        xr = BAR_X0 + BAR_W * self.shown
        _set_verts(self._fill_data, self._pts(BAR_X0, xr, self.zb, self.zt))
        _set_verts(self._band_data, self._pts(BAR_X0, xr, self.zt - BAR_H * BAND_FRACTION, self.zt))
        for np in (self.fill, self.band, self.icon.fill):
            np.setColorScale(tint[0], tint[1], tint[2], 1.0)


class StatBars:
    def __init__(self, app, player) -> None:
        self.player = player
        self.root = None
        parent = getattr(app, "a2dBottomLeft", None)
        if parent is None:
            return
        self.root = parent.attachNewNode("stat-bars")
        self.hp = _Bar(self.root, "hp", HP_Z, _heart_points(),
                       fill=(0.92, 0.12, 0.14, 1.0), band=(0.62, 0.04, 0.08, 1.0),
                       icon_fill=(0.95, 0.15, 0.17, 1.0), icon_outline=(0.20, 0.04, 0.05, 1.0))
        self.stamina = _Bar(self.root, "stamina", STAMINA_Z, BOLT_POINTS,
                            fill=(1.0, 0.80, 0.10, 1.0), band=(0.93, 0.50, 0.08, 1.0),
                            icon_fill=(1.0, 0.80, 0.10, 1.0), icon_outline=(0.22, 0.13, 0.03, 1.0))

    def update(self, dt: float) -> None:
        if self.root is None:
            return
        p = self.player
        self.hp.update(dt, p.health / max(1e-6, p.max_health))

        tint = (1.0, 1.0, 1.0)
        if p.dash_denied_time > 0.0:                      # tried to dash with no stamina: pulse
            pulse = 0.5 + 0.5 * math.sin(p.dash_denied_time * 40.0)
            tint = (1.0, 0.35 + 0.65 * pulse, 0.35 + 0.65 * pulse)
        elif p.stamina < p.dash_stamina_cost:             # can't afford a dash yet: dimmed
            tint = (0.6, 0.6, 0.6)
        self.stamina.update(dt, p.stamina / max(1e-6, p.max_stamina), tint)
