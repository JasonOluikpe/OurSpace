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
