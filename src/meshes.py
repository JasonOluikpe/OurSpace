from __future__ import annotations

import math
import random

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath
)

from src.layout import Box


def make_box(name: str, b: Box, colour, parent: NodePath) -> NodePath:
    x0, y0, x1, y1, z0, z1 = b.x0, b.y0, b.x1, b.y1, b.z0, b.z1
    faces = [
        ((0, 0, -1), [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)]),
        ((0, 0,  1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
        ((0,  1, 0), [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]),
        ((-1, 0, 0), [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]),
        (( 1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
    ]
    vdata = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UHStatic)

    i = 0
    for normal, verts in faces:
        for v in verts:
            vw.addData3(*v)
            nw.addData3(*normal)
            cw.addData4(*colour)
        prim.addVertices(i, i + 1, i + 2)
        prim.addVertices(i, i + 2, i + 3)
        i += 4

    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = NodePath(node)
    np.reparentTo(parent)
    return np


def make_cylinder(name: str, radius: float, height: float, colour, parent: NodePath, segments: int = 28) -> NodePath:
    vdata = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UHStatic)

    for j in range(segments + 1):
        a = 2.0 * math.pi * j / segments
        c, s = math.cos(a), math.sin(a)
        for z in (0.0, height):
            vw.addData3(radius * c, radius * s, z)
            nw.addData3(c, s, 0.0)
            cw.addData4(*colour)
            
    for j in range(segments):
        b = j * 2
        prim.addVertices(b, b + 2, b + 3)
        prim.addVertices(b, b + 3, b + 1)

    base = (segments + 1) * 2
    vw.addData3(0.0, 0.0, height)
    nw.addData3(0.0, 0.0, 1.0)
    cw.addData4(*colour)
    for j in range(segments):
        a = 2.0 * math.pi * j / segments
        vw.addData3(radius * math.cos(a), radius * math.sin(a), height)
        nw.addData3(0.0, 0.0, 1.0)
        cw.addData4(*colour)
    for j in range(segments):
        prim.addVertices(base, base + 1 + (j + 1) % segments, base + 1 + j)

    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = NodePath(node)
    np.reparentTo(parent)
    return np

def make_plank_floor(name: str, boxes, colour, parent: NodePath, plank_w: float = 0.20, min_len: float = 0.9, max_len: float = 1.8, gap: float = 0.008, tone: float = 0.05, z: float = 0.01, seed: int = 7) -> NodePath:
    rng = random.Random(seed)
    vdata = GeomVertexData(name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    cw = GeomVertexWriter(vdata, "color")
    prim = GeomTriangles(Geom.UHStatic)
    i = 0

    for b in boxes:
        y = b.y0
        while y < b.y1 - 1e-6:
            y_end = min(y + plank_w, b.y1)
            row_shade = rng.uniform(-tone * 0.5, tone * 0.5)
            x = b.x0 - rng.uniform(0.0, max_len)          # random stagger per row
            while x < b.x1 - 1e-6:
                length = rng.uniform(min_len, max_len)
                xa, xb = max(x, b.x0), min(x + length, b.x1)
                if xb - xa > 0.05:
                    s = 1.0 + row_shade + rng.uniform(-tone, tone)
                    col = (colour[0] * s, colour[1] * s, colour[2] * s, 1.0)
                    xa2, xb2 = xa + gap / 2, xb - gap / 2
                    ya2, yb2 = y + gap / 2, y_end - gap / 2
                    for vx, vy in ((xa2, ya2), (xb2, ya2), (xb2, yb2), (xa2, yb2)):
                        vw.addData3(vx, vy, z)
                        nw.addData3(0.0, 0.0, 1.0)
                        cw.addData4(*col)
                    prim.addVertices(i, i + 1, i + 2)
                    prim.addVertices(i, i + 2, i + 3)
                    i += 4
                x += length
            y = y_end

    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = NodePath(node)
    np.reparentTo(parent)
    return np


# --------------------------------------------------------------------------------------
# MeshBuilder: accumulates boxes / cylinders / ellipsoids / tubes / pleated sheets into ONE
# GeomNode (one draw call per prop). Colours are authored as "albedo"; `tone` darkens them so
# they land where the scene lighting (ambient 0.72 + key 0.95) makes them look right.
# Transforms use Panda's row-vector convention: new = local * parent.
# --------------------------------------------------------------------------------------
from contextlib import contextmanager

from panda3d.core import Mat4, Point3, TransformState, Vec3


class MeshBuilder:
    def __init__(self, name: str, tone: float = 0.70) -> None:
        self.name = name
        self.tone = tone
        self._v: list[tuple[float, float, float]] = []
        self._n: list[tuple[float, float, float]] = []
        self._c: list[tuple[float, float, float, float]] = []
        self._tris: list[tuple[int, int, int]] = []
        self._m = Mat4.identMat()
        self._stack: list[Mat4] = []

    # ------------------------------------------------------------------ transforms
    @contextmanager
    def at(self, x: float = 0.0, y: float = 0.0, z: float = 0.0,
           h: float = 0.0, p: float = 0.0, r: float = 0.0):
        mat = TransformState.makePosHprScale(
            Point3(x, y, z), Vec3(h, p, r), Vec3(1, 1, 1)).getMat()
        self._stack.append(Mat4(self._m))
        self._m = mat * self._m
        try:
            yield self
        finally:
            self._m = self._stack.pop()

    @contextmanager
    def frame(self, origin, direction):
        """Local +Z points along `direction` and local origin sits at `origin`."""
        o = Vec3(*origin)
        z = Vec3(*direction)
        z.normalize()
        ref = Vec3(0, 0, 1) if abs(z.z) < 0.95 else Vec3(1, 0, 0)
        x = ref.cross(z)
        x.normalize()
        y = z.cross(x)
        mat = Mat4(x.x, x.y, x.z, 0.0,
                   y.x, y.y, y.z, 0.0,
                   z.x, z.y, z.z, 0.0,
                   o.x, o.y, o.z, 1.0)
        self._stack.append(Mat4(self._m))
        self._m = mat * self._m
        try:
            yield self
        finally:
            self._m = self._stack.pop()

    # ------------------------------------------------------------------ low level
    def _col(self, colour):
        t = self.tone
        a = colour[3] if len(colour) > 3 else 1.0
        return (colour[0] * t, colour[1] * t, colour[2] * t, a)

    def _vert(self, p, n, col) -> int:
        wp = self._m.xformPoint(Point3(*p))
        wn = self._m.xformVec(Vec3(*n))
        wn.normalize()
        self._v.append((wp.x, wp.y, wp.z))
        self._n.append((wn.x, wn.y, wn.z))
        self._c.append(col)
        return len(self._v) - 1

    def quad(self, a, b, c, d, colour, normal=None) -> None:
        """Four corners in either winding; the face is oriented by `normal` (or the corner order)."""
        pa, pb, pc, pd = Vec3(*a), Vec3(*b), Vec3(*c), Vec3(*d)
        geo = (pb - pa).cross(pc - pa)
        if normal is None:
            n = Vec3(geo)
        else:
            n = Vec3(*normal)
        n.normalize()
        flip = geo.dot(n) < 0.0
        col = self._col(colour)
        idx = [self._vert(p, n, col) for p in (pa, pb, pc, pd)]
        if flip:
            self._tris.append((idx[0], idx[2], idx[1]))
            self._tris.append((idx[0], idx[3], idx[2]))
        else:
            self._tris.append((idx[0], idx[1], idx[2]))
            self._tris.append((idx[0], idx[2], idx[3]))

    # ------------------------------------------------------------------ primitives
    def box(self, x0, y0, z0, x1, y1, z1, colour) -> None:
        if x1 < x0: x0, x1 = x1, x0
        if y1 < y0: y0, y1 = y1, y0
        if z1 < z0: z0, z1 = z1, z0
        q = self.quad
        q((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), colour, (0, 0, -1))
        q((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), colour, (0, 0, 1))
        q((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), colour, (0, -1, 0))
        q((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), colour, (0, 1, 0))
        q((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), colour, (-1, 0, 0))
        q((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), colour, (1, 0, 0))

    def box_c(self, cx, cy, cz, sx, sy, sz, colour) -> None:
        self.box(cx - sx / 2, cy - sy / 2, cz - sz / 2, cx + sx / 2, cy + sy / 2, cz + sz / 2, colour)

    def cylinder(self, cx, cy, z0, z1, r, colour, segments: int = 20,
                 r_top=None, caps: bool = True) -> None:
        """Vertical cylinder / frustum along local Z."""
        rt = r if r_top is None else r_top
        col = self._col(colour)
        slope = (r - rt) / max(1e-9, (z1 - z0))
        ring_b, ring_t = [], []
        for j in range(segments + 1):
            a = 2.0 * math.pi * j / segments
            c, s = math.cos(a), math.sin(a)
            n = (c, s, slope)
            ring_b.append(self._vert((cx + r * c, cy + r * s, z0), n, col))
            ring_t.append(self._vert((cx + rt * c, cy + rt * s, z1), n, col))
        for j in range(segments):
            self._tris.append((ring_b[j], ring_b[j + 1], ring_t[j + 1]))
            self._tris.append((ring_b[j], ring_t[j + 1], ring_t[j]))
        if caps:
            for z, rr, nz in ((z1, rt, 1.0), (z0, r, -1.0)):
                if rr <= 1e-6:
                    continue
                centre = self._vert((cx, cy, z), (0, 0, nz), col)
                ring = [self._vert((cx + rr * math.cos(2 * math.pi * j / segments),
                                    cy + rr * math.sin(2 * math.pi * j / segments), z),
                                   (0, 0, nz), col) for j in range(segments + 1)]
                for j in range(segments):
                    if nz > 0:
                        self._tris.append((centre, ring[j], ring[j + 1]))
                    else:
                        self._tris.append((centre, ring[j + 1], ring[j]))

    def cyl_between(self, p0, p1, r, colour, segments: int = 12, r1=None, caps: bool = True) -> None:
        d = Vec3(*p1) - Vec3(*p0)
        length = d.length()
        if length < 1e-6:
            return
        with self.frame(p0, d):
            self.cylinder(0.0, 0.0, 0.0, length, r, colour, segments, r_top=r1, caps=caps)

    def ellipsoid(self, cx, cy, cz, rx, ry, rz, colour, rings: int = 8, segments: int = 14) -> None:
        col = self._col(colour)
        grid = []
        for i in range(rings + 1):
            phi = -math.pi / 2 + math.pi * i / rings
            row = []
            for j in range(segments + 1):
                th = 2 * math.pi * j / segments
                x = math.cos(phi) * math.cos(th)
                y = math.cos(phi) * math.sin(th)
                z = math.sin(phi)
                n = (x / rx, y / ry, z / rz)
                row.append(self._vert((cx + rx * x, cy + ry * y, cz + rz * z), n, col))
            grid.append(row)
        for i in range(rings):
            for j in range(segments):
                a, b = grid[i][j], grid[i][j + 1]
                c, d = grid[i + 1][j + 1], grid[i + 1][j]
                self._tris.append((a, b, c))
                self._tris.append((a, c, d))

    def tube(self, points, r, colour, sides: int = 8) -> None:
        """Round pipe swept along a polyline (faucets, hoses)."""
        pts = [Vec3(*p) for p in points]
        col = self._col(colour)
        rings = []
        for i, p in enumerate(pts):
            a = pts[max(0, i - 1)]
            b = pts[min(len(pts) - 1, i + 1)]
            t = b - a
            t.normalize()
            ref = Vec3(0, 0, 1) if abs(t.z) < 0.95 else Vec3(1, 0, 0)
            n1 = t.cross(ref)
            n1.normalize()
            n2 = t.cross(n1)
            ring = []
            for j in range(sides + 1):
                th = 2 * math.pi * j / sides
                n = n1 * math.cos(th) + n2 * math.sin(th)
                q = p + n * r
                ring.append(self._vert((q.x, q.y, q.z), (n.x, n.y, n.z), col))
            rings.append(ring)
        for i in range(len(rings) - 1):
            for j in range(sides):
                a, b = rings[i][j], rings[i][j + 1]
                c, d = rings[i + 1][j + 1], rings[i + 1][j]
                self._tris.append((a, b, c))
                self._tris.append((a, c, d))
                self._tris.append((a, c, b))      # second winding: tube is visible from both sides
                self._tris.append((a, d, c))

    def sheet(self, grid, colours=None, colour=(1, 1, 1, 1)) -> None:
        """Double-sided smooth surface from a rows x cols grid of 3D points (curtains)."""
        rows, cols = len(grid), len(grid[0])
        P = [[Vec3(*p) for p in row] for row in grid]
        normals = [[Vec3(0, 0, 0) for _ in range(cols)] for _ in range(rows)]
        for i in range(rows - 1):
            for j in range(cols - 1):
                n = (P[i][j + 1] - P[i][j]).cross(P[i + 1][j] - P[i][j])
                for (a, b) in ((i, j), (i, j + 1), (i + 1, j), (i + 1, j + 1)):
                    normals[a][b] += n
        for row in normals:
            for n in row:
                if n.length() > 1e-9:
                    n.normalize()
        front, back = [], []
        for i in range(rows):
            fr, bk = [], []
            for j in range(cols):
                col = self._col(colours[i][j] if colours else colour)
                p, n = P[i][j], normals[i][j]
                fr.append(self._vert((p.x, p.y, p.z), (n.x, n.y, n.z), col))
                bk.append(self._vert((p.x, p.y, p.z), (-n.x, -n.y, -n.z), col))
            front.append(fr)
            back.append(bk)
        for i in range(rows - 1):
            for j in range(cols - 1):
                a, b, c, d = front[i][j], front[i][j + 1], front[i + 1][j + 1], front[i + 1][j]
                self._tris.append((a, b, c))
                self._tris.append((a, c, d))
                a, b, c, d = back[i][j], back[i][j + 1], back[i + 1][j + 1], back[i + 1][j]
                self._tris.append((a, c, b))
                self._tris.append((a, d, c))

    # ------------------------------------------------------------------ output
    def build(self, parent: NodePath) -> NodePath:
        vdata = GeomVertexData(self.name, GeomVertexFormat.getV3n3c4(), Geom.UHStatic)
        vdata.setNumRows(len(self._v))
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        cw = GeomVertexWriter(vdata, "color")
        for v, n, c in zip(self._v, self._n, self._c):
            vw.addData3(*v)
            nw.addData3(*n)
            cw.addData4(*c)
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


def make_tile_floor(name: str, b: Box, colour, grout, parent: NodePath, tile: float = 1.2,
                    gap: float = 0.035, tone: float = 0.035, z: float = 0.02, seed: int = 11) -> NodePath:
    """Large square porcelain tiles over a light grout slab (bathroom floor)."""
    rng = random.Random(seed)
    mb = MeshBuilder(name, tone=1.0)
    mb.quad((b.x0, b.y0, z - 0.008), (b.x1, b.y0, z - 0.008), (b.x1, b.y1, z - 0.008),
            (b.x0, b.y1, z - 0.008), grout, (0, 0, 1))
    y = b.y0
    while y < b.y1 - 1e-6:
        y_end = min(y + tile, b.y1)
        x = b.x0
        while x < b.x1 - 1e-6:
            x_end = min(x + tile, b.x1)
            s = 1.0 + rng.uniform(-tone, tone)
            col = (colour[0] * s, colour[1] * s, colour[2] * s, 1.0)
            xa, xb, ya, yb = x + gap / 2, x_end - gap / 2, y + gap / 2, y_end - gap / 2
            mb.quad((xa, ya, z), (xb, ya, z), (xb, yb, z), (xa, yb, z), col, (0, 0, 1))
            x = x_end
        y = y_end
    return mb.build(parent)
