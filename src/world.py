from __future__ import annotations

from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    DirectionalLight,
    LineSegs,
    NodePath,
    TextNode,
    TransparencyAttrib,
    Vec3,
    Vec4
)

from src import layout
from src.collision import CollisionWorld, Rect
from src.debris import DebrisField
from src.doors import DoorManager
from src.fence import Fence
from src.repair import RepairSystem
from src.meshes import make_box


COL_FLOOR   = (0.15, 0.14, 0.13, 1.00)
COL_WALL    = (0.10, 0.10, 0.11, 1.00)
COL_COUNTER = (1.00, 1.00, 1.00, 1.00)
COL_FENCE   = (0.40, 0.40, 0.40, 1.00)
COL_GRID    = (0.32, 0.40, 0.46, 1.00)
COL_OUTSIDE = (0.09, 0.10, 0.10, 1.00)

WALL_FADE_ALPHA = 0.18
WALL_FADE_SPEED = 10.0


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


class World:
    def __init__(self, app) -> None:
        self.app = app
        self.root = app.render.attachNewNode("world")
        self.walls_root = self.root.attachNewNode("walls")
        self._fading: list[_FadingWall] = []

        sx, sy = layout.spawn_point()
        self.spawn = Vec3(sx, sy, 0.0)
        self.player_bounds = layout.walkable_bounds()

        self._build_environment()
        self._build_floor()
        self._build_walls()
        self._build_counter()
        self.debris = DebrisField(self.root)
        self._build_labels()

        self.collision = CollisionWorld(
            [Rect(b.x0, b.y0, b.x1, b.y1) for b in layout.collider_boxes()],
            layout.agent_bounds(),
        )

        self.debris.collision = self.collision
        self.doors = DoorManager(self.app, self.root, self.debris)
        for provider in self.doors.colliders():
            self.collision.add_dynamic(provider)

        self.fence = Fence(self.root, self.debris)
        self.collision.add_dynamic(self.fence.collider)

        self.obstacles = list(self.doors.doors) + [self.fence]
        self.repair = RepairSystem(self.app, self)
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
        self.repair.update(dt, focus.x, focus.y)
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
        self.app.setBackgroundColor(Vec4(0.06, 0.07, 0.08, 1.0))
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
        make_box("floor", layout.floor_box(), COL_FLOOR, self.root)
        make_box("balcony-floor", layout.balcony_box(), COL_FLOOR, self.root)
        make_box("outside", layout.outside_box(), COL_OUTSIDE, self.root)

        x0, y_bot, x1, y_top = layout.walkable_bounds()
        ls = LineSegs("floor-grid")
        ls.setColor(*COL_GRID)
        ls.setThickness(1.0)
        x = x0
        while x <= x1 + 1e-6:
            ls.moveTo(x, y_bot, 0.02)
            ls.drawTo(x, y_top, 0.02)
            x += 1.0
        y = y_bot
        while y <= y_top + 1e-6:
            ls.moveTo(x0, y, 0.02)
            ls.drawTo(x1, y, 0.02)
            y += 1.0
        grid = NodePath(ls.create())
        grid.reparentTo(self.root)
        grid.setLightOff()

    def _build_walls(self) -> None:
        for b in layout.wall_boxes():
            np = make_box("wall", b, COL_WALL, self.walls_root)
            self._fading.append(_FadingWall(np, b))
        for b in layout.rail_boxes():
            make_box("rail", b, COL_WALL, self.walls_root)

    def _build_counter(self) -> None:
        for b in layout.counter_boxes():
            make_box("counter", b, COL_COUNTER, self.root)

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
