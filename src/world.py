from __future__ import annotations

import math
import random

from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    DirectionalLight,
    NodePath,
    TextNode,
    TransparencyAttrib,
    Vec3,
    Vec4
)

from src import layout
from src.collision import CollisionWorld, Rect
from src.debris import DebrisField, Piece
from src.destruction import hits_any
from src.city import City, BG as CITY_BG
from src.doors import DoorManager
from src.fence import Fence
from src import furniture, props
from src.meshes import make_box, make_plank_floor, make_tile_floor


COL_FLOOR   = (0.15, 0.14, 0.13, 1.00)
COL_WALL    = (0.10, 0.10, 0.11, 1.00)
COL_COUNTER = (1.00, 1.00, 1.00, 1.00)
COL_FENCE   = (0.40, 0.40, 0.40, 1.00)
COL_GRID    = (0.32, 0.40, 0.46, 1.00)

WALL_FADE_ALPHA = 0.18
WALL_FADE_SPEED = 10.0

COL_FLOOR   = (0.40, 0.36, 0.31, 1.00)   # greige plank colour (appears ~ (0.60, 0.54, 0.47))
COL_TILE   = (0.92, 0.91, 0.88, 1.00)   # large white porcelain bathroom tiles
COL_GROUT  = (0.66, 0.65, 0.63, 1.00)
COL_SEAM    = (0.24, 0.21, 0.18, 1.00)   # shows through the gaps between planks


def _segment_hits_box(p0: Vec3, p1: Vec3, b: layout.Box, pad: float = 0.05) -> bool:
    lo = (b.x0 - pad, b.y0 - pad, b.z0)
    hi = (b.x1 + pad, b.y1 + pad, b.z1)
    t0, t1 = 0.0, 1.0
    for axis in range(3):
        d = p1[axis] - p0[axis]
        if abs(d) < 1e-9:
            if p0[axis] < lo[axis] or p0[axis] > hi[axis]:
                return False
            continue
        ta = (lo[axis] - p0[axis]) / d
        tb = (hi[axis] - p0[axis]) / d
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return False
    return True


class _FadingWall:
    def __init__(self, np: NodePath, box: layout.Box) -> None:
        self.np = np
        self.box = box
        self.alpha = 1.0


class _Solid:
    """One wall / rail slab. Crushing replaces it with the slabs that are left over."""
    __slots__ = ("box", "np", "fade", "kind")

    def __init__(self, box, np, fade, kind) -> None:
        self.box, self.np, self.fade, self.kind = box, np, fade, kind


CRUSH_CELL = 0.5                  # walls are chopped into slices this long when something smashes through them


class World:
    def __init__(self, app) -> None:
        self.app = app
        self.solids: list[_Solid] = []
        self.props: list = []
        self.on_geometry_changed: list = []        # callbacks(bbox) after walls / furniture were destroyed
        self.root = app.render.attachNewNode("world")
        self.walls_root = self.root.attachNewNode("walls")
        self._fading: list[_FadingWall] = []

        sx, sy = layout.spawn_point()
        self.spawn = Vec3(sx, sy, 0.0)
        self.player_bounds = layout.walkable_bounds()

        self._build_environment()
        self.city = City(self.app.render)       # downtown Toronto around (and below) our floor
        self._build_floor()
        self._build_walls()
        self._build_furniture()
        self.debris = DebrisField(self.root)
        # self._build_labels()

        self.collision = CollisionWorld(self._static_rects(), layout.agent_bounds())

        self.debris.collision = self.collision
        self.doors = DoorManager(self.app, self.root, self.debris)
        for provider in self.doors.colliders():
            self.collision.add_dynamic(provider)

        self.fence = Fence(self.root, self.debris)
        for provider in self.fence.collider_providers():
            self.collision.add_dynamic(provider)
        self.doors.add_toggleable(self.fence)

        self.obstacles = list(self.doors.doors) + [self.fence]
        for np, box in self.doors.fade_targets():
            self._fading.append(_FadingWall(np, box))

    def height_at(self, x: float, y: float) -> float:
        return 0.0

    @property
    def center(self) -> Vec3:
        x0, y0, x1, y1 = layout.walkable_bounds()
        return Vec3((x0 + x1) * 0.5, (y0 + y1) * 0.5, 0.0)

    def update(self, dt: float, camera_pos: Vec3, focus: Vec3) -> None:
        self.doors.update(dt, focus.x, focus.y)
        self.fence.update(dt)
        self.city.update(dt, focus.x, focus.y)
        self.debris.update(dt)
        k = min(1.0, dt * WALL_FADE_SPEED)
        for w in self._fading:
            target = WALL_FADE_ALPHA if _segment_hits_box(camera_pos, focus, w.box) else 1.0
            w.alpha += (target - w.alpha) * k
            if w.alpha > 0.995:
                w.alpha = 1.0
                w.np.setTransparency(TransparencyAttrib.MNone)
                w.np.setDepthWrite(True)
                w.np.clearColorScale()
            else:
                w.np.setTransparency(TransparencyAttrib.MAlpha)
                w.np.setDepthWrite(False)
                w.np.setAlphaScale(w.alpha)

    def _build_environment(self) -> None:
        self.app.setBackgroundColor(Vec4(*CITY_BG))
        self.app.render.setAntialias(AntialiasAttrib.MMultisample)

        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.72, 0.72, 0.70, 1.0))
        self.app.render.setLight(self.app.render.attachNewNode(ambient))

        key = DirectionalLight("key")
        key.setColor(Vec4(0.95, 0.93, 0.88, 1.0))
        key_node = self.app.render.attachNewNode(key)
        key_node.setHpr(-38.0, -55.0, 0.0)
        self.app.render.setLight(key_node)

    def _build_floor(self) -> None:
        room, balcony = layout.floor_box(), layout.balcony_box()
        make_box("floor", room, COL_SEAM, self.root)
        make_box("balcony-floor", balcony, COL_SEAM, self.root)
        make_plank_floor("floor-planks", layout.plank_floor_boxes() + [balcony], COL_FLOOR, self.root, gap=0.004)
        # sits clear above the plank field (z 0.01), otherwise the two coplanar meshes z-fight into a mixture
        make_tile_floor("bathroom-tiles", layout.bathroom_box(), COL_TILE, COL_GROUT, self.root,
                        tile=1.5, gap=0.03, tone=0.008, z=0.03)

    def _build_walls(self) -> None:
        for b in layout.wall_boxes():
            np = make_box("wall", b, COL_WALL, self.walls_root)
            fade = _FadingWall(np, b)
            self._fading.append(fade)
            self.solids.append(_Solid(b, np, fade, "wall"))

        for b in layout.rail_boxes():
            np = make_box("rail", b, COL_WALL, self.walls_root)
            self.solids.append(_Solid(b, np, None, "rail"))

    def _build_furniture(self) -> None:
        fade, self.props = props.build_apartment(self.root)
        for np, box in fade:
            self._fading.append(_FadingWall(np, box))

    # ------------------------------------------------------------------ destruction
    def _static_rects(self) -> list[Rect]:
        rects = [Rect(s.box.x0, s.box.y0, s.box.x1, s.box.y1) for s in self.solids]
        for p in self.props:
            if p.alive:
                rects += p.rects
        return rects

    def crush(self, obbs, source: tuple[float, float]) -> None:
        """Smash everything under the given oriented regions: wall slices, rails, furniture, curtains, doors, gate.
        The remains stay on the floor as debris (it never blocks walking)."""
        pad = 0.2
        bbox = None
        for o in obbs:
            b = o.bbox()
            bbox = b if bbox is None else (min(bbox[0], b[0]), min(bbox[1], b[1]), max(bbox[2], b[2]), max(bbox[3], b[3]))

        # walls and rails
        kept: list[_Solid] = []
        for s in self.solids:
            b = s.box
            if not hits_any(obbs, b.x0, b.y0, b.x1, b.y1):
                kept.append(s)
                continue
            kept += self._split_solid(s, obbs, source)
        self.solids = kept

        # furniture and curtains
        for p in self.props:
            if p.alive and hits_any(obbs, p.area.x0, p.area.y0, p.area.x1, p.area.y1):
                self._destroy_prop(p, source)

        # doors and the gate
        for ob in self.obstacles:
            rect = ob.nav_state()[0]
            if rect is not None and not ob.broken and hits_any(obbs, rect.x0, rect.y0, rect.x1, rect.y1):
                ob.break_(source)

        self.collision.rects = self._static_rects()
        if bbox is not None:
            for fn in self.on_geometry_changed:
                fn((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))

    def _split_solid(self, s: _Solid, obbs, source) -> list[_Solid]:
        b = s.box
        along_x = (b.x1 - b.x0) >= (b.y1 - b.y0)
        lo, hi = (b.x0, b.x1) if along_x else (b.y0, b.y1)
        n = max(1, int(math.ceil((hi - lo) / CRUSH_CELL)))
        step = (hi - lo) / n

        def cell_box(a: float, c: float):
            return (a, b.y0, c, b.y1) if along_x else (b.x0, a, b.x1, c)

        hit = [hits_any(obbs, *cell_box(lo + i * step, lo + (i + 1) * step)) for i in range(n)]
        if not any(hit):
            return [s]

        s.np.removeNode()
        if s.fade is not None and s.fade in self._fading:
            self._fading.remove(s.fade)

        thick = (b.y1 - b.y0) if along_x else (b.x1 - b.x0)
        slices = max(1, int(math.ceil((b.z1 - b.z0) / 1.35)))
        sh = (b.z1 - b.z0) / slices
        pieces = []
        for i in range(n):
            if not hit[i]:
                continue
            mid = lo + (i + 0.5) * step
            cx, cy = (mid, (b.y0 + b.y1) / 2) if along_x else ((b.x0 + b.x1) / 2, mid)
            for k in range(slices):
                pieces.append(Piece((cx, cy, b.z0 + (k + 0.5) * sh), 0.0 if along_x else 90.0,
                                    (step, sh, thick), COL_WALL))
        self.debris.shatter(pieces, source, 1.3)

        out: list[_Solid] = []
        i = 0
        while i < n:
            if hit[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and not hit[j + 1]:
                j += 1
            x0, y0, x1, y1 = cell_box(lo + i * step, lo + (j + 1) * step)
            nb = layout.Box(x0, y0, x1, y1, b.z0, b.z1)
            np = make_box("wall" if s.kind == "wall" else "rail", nb, COL_WALL, self.walls_root)
            fade = None
            if s.kind == "wall":
                fade = _FadingWall(np, nb)
                self._fading.append(fade)
            out.append(_Solid(nb, np, fade, s.kind))
            i = j + 1
        return out

    def _destroy_prop(self, p, source) -> None:
        p.alive = False
        for n in p.nodes:
            self._fading = [w for w in self._fading if w.np != n]
            n.removeNode()
        area = p.area
        w, d = area.x1 - area.x0, area.y1 - area.y0
        count = max(5, min(18, int(w * d * 2.2)))
        pieces = []
        for _ in range(count):
            x = random.uniform(area.x0, area.x1)
            y = random.uniform(area.y0, area.y1)
            z = random.uniform(0.2, max(0.4, p.height * 0.8))
            pw, pd = random.uniform(0.3, 0.9), random.uniform(0.25, 0.8)
            pieces.append(Piece((x, y, z), random.uniform(0, 180), (pw, pd, random.uniform(0.12, 0.35)),
                                random.choice(p.colours)))
        self.debris.shatter(pieces, source, 1.2)

    def _build_labels(self) -> None:
        for text, px, py, size in layout.LABELS:
            x, y = layout.W(px, py)
            tn = TextNode(f"label-{text}")
            tn.setText(text)
            tn.setAlign(TextNode.ACenter)
            tn.setTextColor(1, 1, 1, 0.88)
            tn.setShadow(0.04, 0.04)
            tn.setShadowColor(0, 0, 0, 0.85)
            np = NodePath(tn)
            np.setLightOff()
            np.setTransparency(TransparencyAttrib.MAlpha)
            np.setScale(size)
            np.setP(-90)
            np.setPos(x, y, 0.03)
            np.reparentTo(self.root)
