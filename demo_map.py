from __future__ import annotations

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    DirectionalLight,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LineSegs,
    NodePath,
    TextNode,
    TransparencyAttrib,
    Vec4,
    loadPrcFileData,
)

# --------------------------------------------------------------------------- #
#  Palette
# --------------------------------------------------------------------------- #
COL_FLOOR   = (0.15, 0.14, 0.13, 1.00)
COL_WALL    = (0.10, 0.10, 0.11, 1.00)
COL_RAIL    = (0.10, 0.10, 0.11, 1.00)
COL_COUNTER = (1.00, 1.00, 1.00, 1.00)
COL_GRID    = (0.32, 0.40, 0.46, 1.00)

# --------------------------------------------------------------------------- #
#  Sketch -> world conversion
#  All layout below is written in the pixel coordinates of the sketch, so it
#  can be tweaked by eye. 1 px = PX_X / PX_Y meters. Origin = middle of the front wall.
#  +X = right, +Y = toward the balcony.
# --------------------------------------------------------------------------- #
PX_X = 0.105      # meters per sketch pixel, horizontally (stretched wide)
PX_Y = 0.070      # meters per sketch pixel, vertically
ORIGIN_PX = (615, 537)

DOOR_M = 1.9                  # every doorway is this wide (balcony door excepted)
DX = DOOR_M / PX_X            # door width in sketch px along X
DY = DOOR_M / PX_Y            # door width in sketch px along Y


def W(px, py):
    """sketch pixel -> world (x, y)"""
    return ((px - ORIGIN_PX[0]) * PX_X, (ORIGIN_PX[1] - py) * PX_Y)


# Sketch bounds
ROOM_L, ROOM_R = 443, 787
ROOM_T, ROOM_B = 280, 537
BALC_T = 228

WALL_HEIGHT = 4.0
RAIL_HEIGHT = 1.4
WALL_THICK  = 0.22
COUNTER_H   = 1.6
FENCE_H     = 1.4
COL_FENCE   = (0.40, 0.40, 0.40, 1.00)
FLOOR_THICK = 0.10

# Wall segments (px1, py1, px2, py2). Gaps between segments are doorways.
WALLS = [
    # --- exterior shell
    (443, 537, 625, 537),   # front wall, left of front door
    (625 + DX, 537, 787, 537),   # front wall, right of front door
    (443, 280, 443, 537),   # left wall
    (787, 280, 787, 537),   # right wall
    (443, 280, 480, 280),   # balcony divider, left of sliding door
    (570, 280, 787, 280),   # balcony divider, right of sliding door

    # --- bedroom
    (629, 280 + DY, 629, 440),   # west wall (door gap near the balcony)
    (629, 440, 728, 440),   # south wall, left part
    (728 + DX, 440, 787, 440),   # south wall, right of door

    # --- bathroom
    (688, 440, 688, 479 - DY / 2),
    (688, 479 + DY / 2, 688, 537),

    # --- closet
    (541, 480, 541, 537),
    (541, 480, 587, 480),
    (587, 480, 587, 497),
    (587, 497 + DY, 587, 537),
]

# Low balcony railing
RAILS = [
    (443, 228, 443, 280),
    (787, 228, 787, 280),
    (443, 228, 787, 228),
]

# Dog fence: from the end of the counter arm to the bedroom wall (px x1, x2, y)
FENCE = (560, 629, 396)

# Kitchen counter (L-shape), as pixel rectangles (x1, y1, x2, y2)
COUNTER = [
    (443, 375, 560, 417),   # horizontal arm (flush with left wall)
    (443, 375, 487, 537),   # vertical arm (flush with left + front walls)
]


class RoomPreview(ShowBase):

    # ---- camera ----------------------------------------------------------
    DEFAULT_ZOOM  = 62.0
    DEFAULT_YAW   = 0.0
    DEFAULT_PITCH = -55.0
    MIN_ZOOM = 6.0
    MAX_ZOOM = 260.0
    ZOOM_STEP = 1.12
    ORBIT_SENSITIVITY = 180.0
    MIN_PITCH = -89.0
    MAX_PITCH = -5.0

    def __init__(self):
        loadPrcFileData('', '\n'.join([
            "window-title Arena 3D Preview",
            "win-size 1280 720",
            "framebuffer-multisample 1",
            "multisamples 4",
        ]))
        super().__init__()

        self.r = self.render
        self.disableMouse()

        self.zoom = self.DEFAULT_ZOOM
        self.yaw = self.DEFAULT_YAW
        self.pitch = self.DEFAULT_PITCH
        self._orbiting = False
        self._last_mouse = None

        self.setBackgroundColor(0.06, 0.07, 0.08, 1.0)
        self.setup()

    # ------------------------------------------------------------------ #
    #  Scene
    # ------------------------------------------------------------------ #
    def setup(self):
        self.setup_lighting()
        self.walls = self.r.attachNewNode("walls")
        self.create_floors()
        self.create_floor_grid()
        self.build_walls()
        self.build_counter()
        self.build_fence()
        self.add_labels()
        self.setup_camera()

    def setup_lighting(self):
        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.72, 0.72, 0.70, 1.0))
        self.r.setLight(self.r.attachNewNode(ambient))

        key = DirectionalLight("key-light")
        key.setColor(Vec4(0.95, 0.93, 0.88, 1.0))
        key_node = self.r.attachNewNode(key)
        key_node.setPos(6.0, -7.0, 12.0)
        key_node.setHpr(-38.0, -55.0, 0.0)
        self.r.setLight(key_node)

    # ------------------------------------------------------------------ #
    #  Primitive: flat-coloured box built from raw geometry
    #  (no texture, so no rainbow artefacts; z0 is the bottom, z1 the top)
    # ------------------------------------------------------------------ #
    def make_box(self, name, x0, y0, x1, y1, z0, z1, colour, parent=None):
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
        np.reparentTo(parent if parent is not None else self.r)
        return np

    # ------------------------------------------------------------------ #
    #  Floor (room + balcony slab, same material)
    # ------------------------------------------------------------------ #
    def create_floors(self):
        x0, y1 = W(ROOM_L, ROOM_T)
        x1, y0 = W(ROOM_R, ROOM_B)
        self.make_box("floor", x0, y0, x1, y1, -FLOOR_THICK, 0.0, COL_FLOOR)

        bx0, by1 = W(ROOM_L, BALC_T)
        bx1, by0 = W(ROOM_R, ROOM_T)
        self.make_box("balcony-floor", bx0, by0, bx1, by1,
                      -FLOOR_THICK, 0.0, COL_FLOOR)

    def create_floor_grid(self, step=1.0):
        x0, y_top = W(ROOM_L, BALC_T)
        x1, y_bot = W(ROOM_R, ROOM_B)

        ls = LineSegs("floor-grid")
        ls.setColor(*COL_GRID)
        ls.setThickness(1.0)

        x = x0
        while x <= x1 + 1e-6:
            ls.moveTo(x, y_bot, 0.02)
            ls.drawTo(x, y_top, 0.02)
            x += step
        y = y_bot
        while y <= y_top + 1e-6:
            ls.moveTo(x0, y, 0.02)
            ls.drawTo(x1, y, 0.02)
            y += step

        NodePath(ls.create()).reparentTo(self.r)

    # ------------------------------------------------------------------ #
    #  Walls: bottoms sit exactly on the floor (z = 0)
    # ------------------------------------------------------------------ #
    def add_wall(self, seg, height, colour):
        (ax, ay), (bx, by) = W(seg[0], seg[1]), W(seg[2], seg[3])
        h = WALL_THICK * 0.5
        # extend each end by half a thickness so corners close cleanly
        x0, x1 = min(ax, bx) - h, max(ax, bx) + h
        y0, y1 = min(ay, by) - h, max(ay, by) + h
        self.make_box("wall", x0, y0, x1, y1, 0.0, height, colour, parent=self.walls)

    def build_walls(self):
        for seg in WALLS:
            self.add_wall(seg, WALL_HEIGHT, COL_WALL)
        for seg in RAILS:
            self.add_wall(seg, RAIL_HEIGHT, COL_RAIL)

    # ------------------------------------------------------------------ #
    #  Kitchen counter (only furniture): white, resting on the floor
    # ------------------------------------------------------------------ #
    def build_counter(self):
        for (px1, py1, px2, py2) in COUNTER:
            ax, ay = W(px1, py1)
            bx, by = W(px2, py2)
            self.make_box("counter",
                          min(ax, bx), min(ay, by),
                          max(ax, bx), max(ay, by),
                          0.0, COUNTER_H, COL_COUNTER)

    # ------------------------------------------------------------------ #
    #  Dog fence: rails + pickets, spanning counter end -> wall
    # ------------------------------------------------------------------ #
    def build_fence(self):
        px1, px2, py = FENCE
        xa, y = W(px1, py)
        xb, _ = W(px2, py)
        t = 0.10
        y0, y1 = y - t / 2, y + t / 2
        mk = lambda x0, x1, z0, z1: self.make_box(
            "fence", x0, y0, x1, y1, z0, z1, COL_FENCE)

        # rails
        mk(xa, xb, 0.15, 0.30)
        mk(xa, xb, FENCE_H - 0.20, FENCE_H)
        mk(xa, xb, FENCE_H * 0.5 - 0.075, FENCE_H * 0.5 + 0.075)

        # pickets, evenly spaced, with a post at each end
        n = max(2, int((xb - xa) / 0.55))
        pw = 0.10
        for i in range(n + 1):
            cx = xa + (xb - xa) * i / n
            lo = max(xa, cx - pw / 2)
            hi = min(xb, cx + pw / 2)
            mk(lo, hi, 0.0, FENCE_H)

    # ------------------------------------------------------------------ #
    #  Labels (lie flat on the floor, readable from above)
    # ------------------------------------------------------------------ #
    def add_label(self, text, px, py, size=0.7):
        x, y = W(px, py)
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
        np.reparentTo(self.r)

    def add_labels(self):
        for text, px, py, size in (
            ("LIVING ROOM", 515, 325, 1.00),
            ("KITCHEN",     535, 450, 0.65),
            ("BEDROOM",     710, 365, 1.00),
            ("BATHROOM",    738, 490, 0.75),
            ("CLOSET",      564, 515, 0.48),
            ("ENTRY",       645, 500, 0.60),
            ("BALCONY",     615, 258, 1.00),
        ):
            self.add_label(text, px, py, size)

    # ------------------------------------------------------------------ #
    #  Camera: orbit + zoom
    # ------------------------------------------------------------------ #
    def setup_camera(self):
        self.camLens.setNearFar(0.1, 1000.0)
        self.camLens.setFov(55.0)

        cx, cy = W((ROOM_L + ROOM_R) / 2, (BALC_T + ROOM_B) / 2)
        self.cam_pivot = self.r.attachNewNode("cam-pivot")
        self.cam_pivot.setPos(cx, cy, 0.0)
        self.camera.reparentTo(self.cam_pivot)

        self.accept("wheel_up", self.zoom_in)
        self.accept("wheel_down", self.zoom_out)

        for key in ("=", "+", "page_up"):
            self.accept(key, self.zoom_in)
        for key in ("-", "_", "page_down"):
            self.accept(key, self.zoom_out)
        self.accept("r", self.reset_camera)
        self.accept("w", self.toggle_walls)

        self.accept("mouse3", self.begin_orbit)
        self.accept("mouse3-up", self.end_orbit)
        self.taskMgr.add(self.orbit_task, "orbit-task")

        self.update_camera()

    def update_camera(self):
        self.cam_pivot.setHpr(self.yaw, self.pitch, 0.0)
        self.camera.setPos(0.0, -self.zoom, 0.0)
        self.camera.setHpr(0.0, 0.0, 0.0)

    def set_zoom(self, value):
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, value))
        self.update_camera()

    def zoom_in(self):
        self.set_zoom(self.zoom / self.ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom * self.ZOOM_STEP)

    def reset_camera(self):
        self.zoom = self.DEFAULT_ZOOM
        self.yaw = self.DEFAULT_YAW
        self.pitch = self.DEFAULT_PITCH
        self.update_camera()

    def toggle_walls(self):
        self.walls.toggleVis()

    def begin_orbit(self):
        self._orbiting = True
        self._last_mouse = None

    def end_orbit(self):
        self._orbiting = False
        self._last_mouse = None

    def orbit_task(self, task):
        if not self._orbiting or not self.mouseWatcherNode.hasMouse():
            return task.cont

        m = self.mouseWatcherNode.getMouse()
        cur = (m.getX(), m.getY())
        if self._last_mouse is not None:
            dx = cur[0] - self._last_mouse[0]
            dy = cur[1] - self._last_mouse[1]
            self.yaw -= dx * self.ORBIT_SENSITIVITY
            self.pitch = max(self.MIN_PITCH,
                             min(self.MAX_PITCH,
                                 self.pitch + dy * self.ORBIT_SENSITIVITY))
            self.update_camera()
        self._last_mouse = cur
        return task.cont


if __name__ == "__main__":
    RoomPreview().run()