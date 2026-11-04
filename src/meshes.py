from __future__ import annotations

from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
)

from src.layout import Box


def make_box(name: str, b: Box, colour, parent: NodePath) -> NodePath:
    """Flat-coloured, textureless box. z0 = bottom, z1 = top."""
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