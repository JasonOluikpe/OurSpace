import math
import random

from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
    Vec3,
    Vec4,
)


class World:
    def __init__(self, app) -> None:
        self.app = app
        self.radius = 7.0
        self.play_radius = 5.9
        self.root = app.render.attachNewNode("world")
        self.spawn = Vec3(0.0, 0.0, 0.02)

        self._build_environment()
        self._build_arena()

    # ------------------------------------------------------------------ queries
    def height_at(self, x: float, y: float) -> float:
        return 0.0

    # ------------------------------------------------------------------ visuals
    def _build_environment(self) -> None:
        self.app.setBackgroundColor(Vec4(0.0, 0.0, 0.0, 1.0))
        self.app.render.setAntialias(AntialiasAttrib.MMultisample)

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.72, 0.72, 0.72, 1.0))
        self.app.render.setLight(self.app.render.attachNewNode(ambient))

        key = DirectionalLight("key")
        key.setColor(Vec4(0.95, 0.93, 0.88, 1.0))
        key_node = self.app.render.attachNewNode(key)
        key_node.setHpr(-38.0, -55.0, 0.0)
        self.app.render.setLight(key_node)

    def _make_triangle_soup(
        self,
        name: str,
        triangles: list[tuple[Vec3, Vec3, Vec3]],
        base: Vec4,
        rng: random.Random,
        light_bias: float = 0.0,
    ) -> NodePath:
        fmt = GeomVertexFormat.getV3n3c4()
        vdata = GeomVertexData(name, fmt, Geom.UHStatic)
        vwriter = GeomVertexWriter(vdata, "vertex")
        nwriter = GeomVertexWriter(vdata, "normal")
        cwriter = GeomVertexWriter(vdata, "color")
        prim = GeomTriangles(Geom.UHStatic)

        index = 0
        for a, b, c in triangles:
            normal = (b - a).cross(c - a)
            if normal.lengthSquared() < 1e-12:
                continue
            normal.normalize()

            # The arena is unlit; bake a small amount of directional shading
            # into the vertex colors so the flat facets remain readable.
            shade = 0.80 + 0.16 * max(0.0, normal.z)
            shade += 0.05 * normal.x - 0.04 * normal.y + light_bias
            shade *= rng.uniform(0.985, 1.015)
            shade = max(0.35, min(1.15, shade))
            color = Vec4(
                min(1.0, base.x * shade),
                min(1.0, base.y * shade),
                min(1.0, base.z * shade),
                1.0,
            )

            for vertex in (a, b, c):
                vwriter.addData3(vertex)
                nwriter.addData3(normal)
                cwriter.addData4(color)
            prim.addVertices(index, index + 1, index + 2)
            index += 3

        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode(name)
        node.addGeom(geom)
        result = NodePath(node)
        result.reparentTo(self.root)
        result.setLightOff()
        return result

    def _build_arena(self) -> None:
        segments = 32

        # Three concentric floor bands give the flat disk a subtle low-poly read.
        # Each band is one flat shade, so there are no radiating pie slices.
        bands = (
            (0.0, 2.5, Vec4(0.76, 0.75, 0.72, 1.0)),
            (2.5, 5.0, Vec4(0.72, 0.71, 0.68, 1.0)),
            (5.0, 6.55, Vec4(0.68, 0.67, 0.64, 1.0)),
        )

        def point(radius: float, angle: float) -> Vec3:
            return Vec3(radius * math.cos(angle), radius * math.sin(angle), 0.0)

        self.floor_bands: list[NodePath] = []
        for band_index, (inner_r, outer_r, color) in enumerate(bands):
            triangles: list[tuple[Vec3, Vec3, Vec3]] = []
            for i in range(segments):
                a0 = 2.0 * math.pi * i / segments
                a1 = 2.0 * math.pi * (i + 1) / segments

                if inner_r <= 1e-6:
                    triangles.append(
                        (Vec3(0.0, 0.0, 0.0), point(outer_r, a0), point(outer_r, a1))
                    )
                else:
                    p_in0 = point(inner_r, a0)
                    p_in1 = point(inner_r, a1)
                    p_out0 = point(outer_r, a0)
                    p_out1 = point(outer_r, a1)
                    triangles.append((p_in0, p_out0, p_out1))
                    triangles.append((p_in0, p_out1, p_in1))

            self.floor_bands.append(
                self._make_triangle_soup(
                    f"arena-floor-{band_index}",
                    triangles,
                    color,
                    random.Random(20 + band_index),
                    light_bias=0.02,
                )
            )

        # A darker ring just inside the edge, plus the visible outer rim.
        rim_tris: list[tuple[Vec3, Vec3, Vec3]] = []
        rim_inner = 6.55
        rim_outer = 7.0
        for i in range(segments):
            a0 = 2.0 * math.pi * i / segments
            a1 = 2.0 * math.pi * (i + 1) / segments
            p_in0 = point(rim_inner, a0)
            p_in1 = point(rim_inner, a1)
            p_out0 = point(rim_outer, a0)
            p_out1 = point(rim_outer, a1)
            rim_tris.append((p_in0, p_out0, p_out1))
            rim_tris.append((p_in0, p_out1, p_in1))

        self.rim = self._make_triangle_soup(
            "arena-rim",
            rim_tris,
            Vec4(0.42, 0.42, 0.41, 1.0),
            random.Random(12),
        )

        # A short side wall makes the arena read as a solid floating platform.
        side_tris: list[tuple[Vec3, Vec3, Vec3]] = []
        depth = -0.55
        for i in range(segments):
            a0 = 2.0 * math.pi * i / segments
            a1 = 2.0 * math.pi * (i + 1) / segments
            top0 = Vec3(7.0 * math.cos(a0), 7.0 * math.sin(a0), 0.0)
            top1 = Vec3(7.0 * math.cos(a1), 7.0 * math.sin(a1), 0.0)
            bot0 = Vec3(top0.x, top0.y, depth)
            bot1 = Vec3(top1.x, top1.y, depth)
            side_tris.append((bot0, bot1, top1))
            side_tris.append((bot0, top1, top0))

        self.side = self._make_triangle_soup(
            "arena-side",
            side_tris,
            Vec4(0.30, 0.30, 0.29, 1.0),
            random.Random(13),
        )
