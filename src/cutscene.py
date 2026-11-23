"""Monitor alert + the WeChat cut scene.

Flow: 10 s after the game starts a red "!" appears over the desk monitor. Standing near it and pressing
E (or Triangle) fades to black, freezes the game, stops drawing the 3D world and plays a fake WeChat
(PC) window: a chat with Klesa about silly Anna photos, then a mouse cursor clicks the BP chat, which
shows three creepy messages. Afterwards it fades back into the (unfrozen) game.
"""
from __future__ import annotations

import base64
import math
import os
from typing import Callable, Optional

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    CardMaker, CullBinManager, Filename, PNMImage, StringStream, Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
    GeomVertexWriter, NodePath, Point3, TextNode, Texture, TransparencyAttrib, Vec3, Vec4,
)

from src import furniture as F
from src.layout import Box
from src.meshes import make_box

# ------------------------------------------------------------------------------------------ tuning
ALERT_DELAY = 1             # seconds after game start; 1 second for debug
INTERACT_REACH = 2.6        # metres from the monitor

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "chat")
FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

# Conversation scrip. (delay_before, kind, side, payload); side "me" = right/green, "them" = left/white.
KLESA_SCRIPT = [
    (0.0, "stamp", None, "6:33 PM"),
    (1.4, "image", "me", "assets/anna 2.png"),
    (0.5, "text", "me", "look at this dog LOL HAHA"),
    (1.2, "text", "them", "AHAHAH she looks like a pencil dog"),
    (1.7, "text", "them", "btw your boyfriend is really hot"),
    (1.5, "text", "me", "LMAOO i know right??"),
    (1.6, "text", "me", "wait what")
]

BP_HISTORY = [ 
    (0.0, "stamp", None, "6:47 PM"),
    (0.0, "text", "them", "Hey I found your address."),
    (0.0, "text", "them", "I'm coming over to give you presents."),
    (0.0, "text", "them", "See you soon!")
]

BP_LIVE = [
    (1.0, "typesend", "me", "NO!!"),
    (1.4, "text", "them", "What is your problem? Anyways i'm already here."),
    (1.9, "text", "them", "Security isn't letting me up though."),
    (1.9, "text", "them", "No problem at all, I'll just come up myself.")
]

# ------------------------------------------------------------------------------------------ 2D layout (canvas px)
CANVAS_H = 720.0
W, H = 1000, 600
NAV_W, LIST_W = 50, 250
CHAT_X = NAV_W + LIST_W
CHAT_W = W - CHAT_X
HEAD_H, INPUT_H = 50, 150
VIS_H = H - HEAD_H - INPUT_H
ROW_Y0, ROW_H = 60, 60

NAV = (0.15, 0.15, 0.15, 1)
LIST_BG = (0.19, 0.19, 0.19, 1)
LIST_PIN = (0.235, 0.235, 0.235, 1)
LIST_HOVER = (0.27, 0.27, 0.27, 1)
LIST_SEL = (0.31, 0.31, 0.31, 1)
CHAT_BG = (0.93, 0.93, 0.93, 1)
HEAD_BG = (0.955, 0.955, 0.955, 1)
LINE_COL = (0.84, 0.84, 0.84, 1)
GREEN = (0.69, 0.89, 0.49, 1)
WHITE = (1, 1, 1, 1)
INK = (0.10, 0.10, 0.10, 1)
GREY_TXT = (0.55, 0.55, 0.55, 1)
ICON = (0.45, 0.45, 0.45, 1)
SEND_IDLE = (0.96, 0.96, 0.96, 1)
SEND_READY = (0.07, 0.76, 0.40, 1)
SEND_PRESSED = (0.04, 0.60, 0.30, 1)

BIN = "wechat"
L_BG, L_PANE, L_MSG, L_BAR, L_BAR_TXT, L_CURSOR, L_FADE = 0, 10, 20, 30, 40, 60, 100


def _ensure_bin() -> None:
    mgr = CullBinManager.getGlobalPtr()
    if mgr.findBin(BIN) < 0:
        mgr.addBin(BIN, CullBinManager.BTFixed, 60)       # after every default bin (gui is "unsorted" = 50)


def _style(np: NodePath, layer: int) -> NodePath:
    np.setBin(BIN, layer)
    np.setDepthTest(False)
    np.setDepthWrite(False)
    return np


def _rect(parent, x, y, w, h, color, layer) -> NodePath:
    cm = CardMaker("r")
    cm.setFrame(0, w, -h, 0)
    np = parent.attachNewNode(cm.generate())
    np.setPos(x, 0, -y)
    np.setColor(*color)
    return _style(np, layer)


def _poly(parent, pts, color, layer, tris=None) -> NodePath:
    """Convex polygon (fan) or an explicit triangle list. Points are (x, y) canvas coords, y down."""
    vd = GeomVertexData("poly", GeomVertexFormat.getV3c4(), Geom.UHStatic)
    vw, cw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "color")
    prim = GeomTriangles(Geom.UHStatic)
    if tris is None:
        n = len(pts)
        cx, cy = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
        vw.addData3(cx, 0, -cy)
        cw.addData4(*color)
        for p in pts:
            vw.addData3(p[0], 0, -p[1])
            cw.addData4(*color)
        for i in range(n):
            prim.addVertices(0, 1 + i, 1 + (i + 1) % n)
    else:
        for t in tris:
            base = vd.getNumRows()
            for p in t:
                vw.addData3(p[0], 0, -p[1])
                cw.addData4(*color)
            prim.addVertices(base, base + 1, base + 2)
    geom = Geom(vd)
    geom.addPrimitive(prim)
    node = GeomNode("poly")
    node.addGeom(geom)
    return _style(parent.attachNewNode(node), layer)


def _circle_pts(cx, cy, r, n=28):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _rrect_pts(x, y, w, h, r, seg=5):
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _lines(parent, pts, color, thickness, layer, closed=False) -> NodePath:
    """Polyline drawn as thin quads (renders identically on every backend, scales with the UI)."""
    pts = list(pts) + ([pts[0]] if closed else [])
    half = max(thickness, 1.3) / 2.0
    tris = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy)
        if n < 1e-6:
            continue
        nx, ny = -dy / n * half, dx / n * half
        a, b = (x0 + nx, y0 + ny), (x0 - nx, y0 - ny)
        c, d = (x1 - nx, y1 - ny), (x1 + nx, y1 + ny)
        tris.append((a, b, c))
        tris.append((a, c, d))
    return _poly(parent, None, color, layer, tris=tris)


def _smooth(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3.0 - 2.0 * p)


# ============================================================================================ world prop
class MonitorAlert:
    """Red billboard "!" floating above the desk monitor. Never hidden by walls."""

    def __init__(self, app) -> None:
        tmp = app.render.attachNewNode("tmp-desk")
        tmp.setPos(F.DESK.x, F.DESK.y, 0.0)
        tmp.setH(F.DESK.h)
        top = app.render.getRelativePoint(tmp, Point3(0.15, 0.12, 1.50 + 0.98))   # top of the monitor
        tmp.removeNode()
        self.xy = (top.x, top.y)
        self.base = Vec3(top.x, top.y, top.z + 0.75)

        self.root = app.render.attachNewNode("monitor-alert")
        self.root.setPos(self.base)
        self.body = self.root.attachNewNode("bang")
        self.body.setBillboardPointEye()
        white, red = (1, 1, 1, 1), (0.93, 0.10, 0.10, 1)
        for grow, col, layer in ((0.06, white, 50), (0.0, red, 51)):
            for z0, z1 in ((0.58, 1.50), (0.0, 0.34)):
                np = make_box("bang-part", Box(-0.18 - grow, -0.04, 0.18 + grow, 0.04, z0 - grow, z1 + grow), col, self.body)
                np.setLightOff()
                np.setTwoSided(True)
                _style(np, layer).setBin("fixed", layer)    # always on top, like a floating marker
        self.body.setZ(-0.75)                                 # pivot around the mark's middle
        self.root.hide()
        self.t = 0.0

    def show(self) -> None:
        self.root.show()

    def hide(self) -> None:
        self.root.hide()

    def update(self, dt: float) -> None:
        self.t += dt
        self.root.setZ(self.base.z + 0.14 * math.sin(self.t * 4.0))
        s = 1.0 + 0.06 * math.sin(self.t * 8.0)
        self.root.setScale(s)

    def destroy(self) -> None:
        self.root.removeNode()


def _find_asset(filename: str) -> Optional[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (os.path.join(here, "..", "assets", "chat"), os.path.join(os.getcwd(), "assets", "chat"),
                 os.path.join(here, "assets", "chat"), os.path.join(here, "..", "assets"), here):
        path = os.path.normpath(os.path.join(base, filename))
        if os.path.isfile(path):
            return path
    return None


_TEX_CACHE: dict[str, tuple] = {}


def _load_chat_texture(filename: str) -> Optional[tuple]:
    """PNMImage -> Texture. Reads assets/chat/<file> if present, else the copy embedded in chat_images.py."""
    if filename in _TEX_CACHE:
        return _TEX_CACHE[filename]
    img = PNMImage()
    ok = False
    path = _find_asset(filename)
    if path is not None:
        ok = img.read(Filename.fromOsSpecific(path))
    if not ok:
        try:
            from src.chat_images import IMAGES
            data = base64.b64decode("".join(IMAGES[filename]))
            ok = img.read(StringStream(data), filename)
        except Exception as exc:
            print(f"[cutscene] could not load picture '{filename}': {exc}")
            return None
    if not ok:
        return None
    # power-of-two texture (works on every renderer); the display aspect comes from the original size
    pot = PNMImage(512, 512)
    pot.quickFilterFrom(img)
    tex = Texture(filename)
    tex.load(pot)
    tex.setMinfilter(Texture.FTLinearMipmapLinear)
    tex.setMagfilter(Texture.FTLinear)
    _TEX_CACHE[filename] = (tex, img.getYSize() / max(1, img.getXSize()))    # (texture, height / width)
    return _TEX_CACHE[filename]


# ============================================================================================ chat pane
class _Chat:
    """One conversation's message column. Lays bubbles out top to bottom and fades them in."""

    def __init__(self, ui: "WeChatUI", parent: NodePath) -> None:
        self.ui = ui
        self.root = parent.attachNewNode("chat")
        self.cy = 12.0
        self.fading: list[list] = []        # [node, age]
        self.scroll = 0.0

    @property
    def target_scroll(self) -> float:
        return max(0.0, self.cy - VIS_H + 8.0)

    def _item(self) -> NodePath:
        n = self.root.attachNewNode("item")
        n.setColorScale(1, 1, 1, 0)
        self.fading.append([n, 0.0])
        return n

    def add_stamp(self, s: str) -> None:
        item = self._item()
        self.ui.text(item, s, CHAT_W / 2, self.cy + 12, 12, GREY_TXT, TextNode.ACenter, L_MSG)
        self.cy += 30

    def add_text(self, side: str, s: str) -> None:
        item = self._item()
        size, padx, pady = 15, 12, 9
        tn = TextNode("measure")
        tn.setText(s)
        if self.ui.font:
            tn.setFont(self.ui.font)
        tn.setWordwrap(380 / size)
        tw, th = (tn.getRight() - tn.getLeft()) * size, (tn.getTop() - tn.getBottom()) * size
        bw, bh = tw + 2 * padx, max(38.0, th + 2 * pady)
        mine = side == "me"
        bx = CHAT_W - 24 - bw if mine else 24
        col = GREEN if mine else WHITE
        _poly(item, _rrect_pts(bx, self.cy, bw, bh, 4), col, L_MSG)
        if mine:
            tail = [(bx + bw - 1, self.cy + 13), (bx + bw + 6, self.cy + 18), (bx + bw - 1, self.cy + 23)]
        else:
            tail = [(bx + 1, self.cy + 13), (bx - 6, self.cy + 18), (bx + 1, self.cy + 23)]
        _poly(item, tail, col, L_MSG)
        base = self.cy + (bh - th) / 2 + tn.getTop() * size
        node, _ = self.ui.text(item, s, bx + padx - tn.getLeft() * size, base, size, INK, TextNode.ALeft, L_MSG + 1,
                               wrap=380)
        self.cy += bh + 14

    def add_image(self, side: str, filename: str) -> None:
        item = self._item()
        w, h = 240.0, 180.0
        loaded = _load_chat_texture(filename)
        tex = loaded[0] if loaded else None
        if loaded:
            h = w * loaded[1]
        bx = CHAT_W - 24 - w if side == "me" else 24
        card = _rect(item, bx, self.cy, w, h, (0.78, 0.78, 0.78, 1), L_MSG)
        if tex is not None:
            card.setColor(1, 1, 1, 1)
            card.setTexture(tex)
        self.cy += h + 14

    def settle(self) -> None:
        """Show everything as already there: no fade-in, scrolled straight to the latest message."""
        for f in self.fading:
            f[0].setColorScale(1, 1, 1, 1)
        self.fading = []
        self.scroll = self.target_scroll

    def update(self, dt: float) -> None:
        for f in self.fading:
            f[1] += dt
            f[0].setColorScale(1, 1, 1, min(1.0, f[1] / 0.25))
        self.fading = [f for f in self.fading if f[1] < 0.25]
        k = min(1.0, dt * 9.0)
        self.scroll += (self.target_scroll - self.scroll) * k


# ============================================================================================ the WeChat window
CONTACTS = (("Klesa", True), ("Ember's Mom", True), ("BP", False), ("Ella", False), ("Lorianne", False), ("Yvonne", False))


class WeChatUI:
    def __init__(self, app) -> None:
        _ensure_bin()
        self.app = app
        self.font = self._load_font()
        self.t = 0.0

        self.ui = app.render2d.attachNewNode("wechat-ui")
        self.ui.setTransparency(TransparencyAttrib.MAlpha)
        _rect(self.ui, -4000, -2000, 8000, 4000, (0.02, 0.02, 0.03, 1), L_BG)        # black backdrop
        self.win = self.ui.attachNewNode("win")
        self.win.setPos(-W / 2, 0, H / 2)

        self.rows: dict[str, dict] = {}
        self.selected = "Klesa"
        self.pressed: Optional[str] = None
        self.cursor_xy = (700.0, 330.0)
        self._build_nav()
        self._build_list()
        self._build_chat_frame()

        self.chats = {"Klesa": _Chat(self, self.win), "BP": _Chat(self, self.win)}
        for c in self.chats.values():
            c.root.setPos(CHAT_X, 0, -HEAD_H)
        self.chats["BP"].root.hide()
        self.active = "Klesa"
        self._build_cursor()
        self.ui.hide()

    # ------------------------------------------------------------------ helpers
    def _load_font(self):
        for p in FONT_CANDIDATES:
            if os.path.exists(p):
                f = self.app.loader.loadFont(Filename.fromOsSpecific(p).getFullpath())
                if f is not None and f.isValid():
                    f.setPixelsPerUnit(64)
                    f.setPageSize(512, 512)
                    return f
        return None

    def text(self, parent, s, x, y, size, color, align=TextNode.ALeft, layer=L_BAR_TXT, wrap=None):
        """y is the text baseline (canvas px, y down)."""
        tn = TextNode("t")
        tn.setText(s)
        tn.setTextColor(*color)
        tn.setAlign(align)
        if self.font:
            tn.setFont(self.font)
        if wrap:
            tn.setWordwrap(wrap / size)
        np = parent.attachNewNode(tn)
        np.setScale(size)
        np.setPos(x, 0, -y)
        _style(np, layer)
        return np, tn

    def _center_text(self, parent, s, x, yc, size, color, align=TextNode.ALeft, layer=L_BAR_TXT):
        return self.text(parent, s, x, yc + 0.34 * size, size, color, align, layer)

    # ------------------------------------------------------------------ static chrome
    def _build_nav(self) -> None:
        w = self.win
        _rect(w, 0, 0, NAV_W, H, NAV, L_PANE)
        _rect(w, 11, 12, 28, 28, (0.62, 0.38, 0.28, 1), L_PANE + 1)                 # own avatar (plain tile)
        _poly(w, _circle_pts(25, 86, 13), (0.03, 0.76, 0.38, 1), L_PANE + 1)         # chats (active)
        _poly(w, _circle_pts(21, 84, 5), WHITE, L_PANE + 2)
        _poly(w, _circle_pts(30, 88, 4), WHITE, L_PANE + 2)
        _lines(w, _circle_pts(25, 134, 5, 16), (0.62, 0.62, 0.62, 1), 1.6, L_PANE + 1, closed=True)   # contacts
        _lines(w, [(14, 152), (16, 144), (34, 144), (36, 152)], (0.62, 0.62, 0.62, 1), 1.6, L_PANE + 1)
        _lines(w, _circle_pts(25, 566, 8, 18), (0.62, 0.62, 0.62, 1), 1.6, L_PANE + 1, closed=True)   # settings
        _lines(w, _circle_pts(25, 566, 3, 10), (0.62, 0.62, 0.62, 1), 1.4, L_PANE + 1, closed=True)

    def _build_list(self) -> None:
        w = self.win
        _rect(w, NAV_W, 0, LIST_W, H, LIST_BG, L_PANE)
        _rect(w, NAV_W + 10, 18, 190, 28, (0.27, 0.27, 0.27, 1), L_PANE + 1)          # search box
        self._center_text(w, "Search", NAV_W + 40, 32, 13, (0.62, 0.62, 0.62, 1), layer=L_PANE + 2)
        _lines(w, _circle_pts(NAV_W + 26, 31, 4.5, 14), (0.62, 0.62, 0.62, 1), 1.3, L_PANE + 2, closed=True)
        _lines(w, [(NAV_W + 30, 35), (NAV_W + 34, 39)], (0.62, 0.62, 0.62, 1), 1.3, L_PANE + 2)
        _lines(w, [(NAV_W + 220, 24), (NAV_W + 220, 40)], (0.75, 0.75, 0.75, 1), 1.6, L_PANE + 2)   # "+"
        _lines(w, [(NAV_W + 212, 32), (NAV_W + 228, 32)], (0.75, 0.75, 0.75, 1), 1.6, L_PANE + 2)

        for i, (name, pinned) in enumerate(CONTACTS):
            y = ROW_Y0 + i * ROW_H
            base = LIST_PIN if pinned else LIST_BG
            bg = _rect(w, NAV_W, y, LIST_W, ROW_H, base, L_PANE + 1)
            if pinned:
                _poly(w, [(NAV_W + LIST_W - 13, y), (NAV_W + LIST_W, y), (NAV_W + LIST_W, y + 13)],
                      (0.42, 0.42, 0.42, 1), L_PANE + 2)
            _, tn = self._center_text(w, name, NAV_W + 20, y + ROW_H / 2, 16, (0.93, 0.93, 0.93, 1), layer=L_PANE + 3)
            row = {"bg": bg, "base": base, "y": y, "badge": []}
            if name == "BP":
                bx = NAV_W + 20 + tn.getWidth() * 16 + 18
                row["badge"].append(_poly(w, _circle_pts(bx, y + ROW_H / 2, 10), (0.98, 0.31, 0.31, 1), L_PANE + 3))
                row["badge"].append(self._center_text(w, "3", bx, y + ROW_H / 2, 12, WHITE, TextNode.ACenter, L_PANE + 4)[0])
            self.rows[name] = row
        self._paint_rows()

    def _build_chat_frame(self) -> None:
        w = self.win
        _rect(w, CHAT_X, 0, CHAT_W, H, CHAT_BG, L_PANE)
        # header + input area sit above the scrolling messages, so overflow is simply covered
        _rect(w, CHAT_X, 0, CHAT_W, HEAD_H, HEAD_BG, L_BAR)
        _rect(w, CHAT_X, HEAD_H - 1, CHAT_W, 1, LINE_COL, L_BAR + 1)
        # scrolling messages can slide past the window edges while they ease into place: mask above/below the window
        backdrop = (0.02, 0.02, 0.03, 1)
        _rect(w, -4000, -2000, 8000, 2000, backdrop, L_BAR + 2)
        _rect(w, -4000, H, 8000, 2000, backdrop, L_BAR + 2)
        self.title = None
        self.title_decor: list[NodePath] = []
        self._set_title("Klesa")
        mx = W - 85
        _lines(w, [(mx - 5, 22), (mx + 5, 22)], (0.35, 0.35, 0.35, 1), 1.3, L_BAR_TXT)        # minimise
        _lines(w, [(W - 55, 17), (W - 45, 17), (W - 45, 27), (W - 55, 27)], (0.35, 0.35, 0.35, 1), 1.3, L_BAR_TXT, True)
        _lines(w, [(W - 30, 17), (W - 20, 27)], (0.35, 0.35, 0.35, 1), 1.3, L_BAR_TXT)        # close
        _lines(w, [(W - 20, 17), (W - 30, 27)], (0.35, 0.35, 0.35, 1), 1.3, L_BAR_TXT)

        iy = H - INPUT_H
        _rect(w, CHAT_X, iy, CHAT_W, INPUT_H, WHITE, L_BAR)
        _rect(w, CHAT_X, iy, CHAT_W, 1, LINE_COL, L_BAR + 1)
        ty = iy + 20
        _lines(w, _circle_pts(CHAT_X + 20, ty, 8, 18), ICON, 1.4, L_BAR_TXT, closed=True)      # smiley
        _poly(w, _circle_pts(CHAT_X + 17, ty - 2, 1.1, 6), ICON, L_BAR_TXT)
        _poly(w, _circle_pts(CHAT_X + 23, ty - 2, 1.1, 6), ICON, L_BAR_TXT)
        _lines(w, [(CHAT_X + 16, ty + 3), (CHAT_X + 20, ty + 5.5), (CHAT_X + 24, ty + 3)], ICON, 1.2, L_BAR_TXT)
        sx = CHAT_X + 48                                                                       # scissors
        _lines(w, [(sx - 6, ty - 8), (sx + 6, ty + 5)], ICON, 1.4, L_BAR_TXT)
        _lines(w, [(sx + 6, ty - 8), (sx - 6, ty + 5)], ICON, 1.4, L_BAR_TXT)
        _lines(w, _circle_pts(sx - 5, ty + 7, 3, 10), ICON, 1.3, L_BAR_TXT, closed=True)
        _lines(w, _circle_pts(sx + 5, ty + 7, 3, 10), ICON, 1.3, L_BAR_TXT, closed=True)
        px = CHAT_X + 76                                                                       # history
        _lines(w, [(px - 6, ty - 4), (px + 6, ty - 4), (px + 6, ty + 8), (px - 6, ty + 8)], ICON, 1.3, L_BAR_TXT, True)
        _lines(w, [(px - 3, ty - 7), (px + 9, ty - 7), (px + 9, ty + 5)], ICON, 1.3, L_BAR_TXT)

        bx, by = CHAT_X + CHAT_W - 78, H - 35
        _rect(w, bx - 1, by - 1, 70, 27, (0.85, 0.85, 0.85, 1), L_BAR + 1)
        self.send_bg = _rect(w, bx, by, 68, 25, SEND_IDLE, L_BAR + 2)
        _, self.send_tn = self._center_text(w, "Send(S)", bx + 34, by + 12.5, 13, (0.32, 0.32, 0.32, 1),
                                            TextNode.ACenter, L_BAR_TXT)
        self.send_xy = (bx + 34.0, by + 12.5)
        self.caret = _rect(w, CHAT_X + 14, iy + 36, 1.3, 17, INK, L_BAR_TXT)
        self.input_np, self.input_tn = self.text(w, "", CHAT_X + 14, iy + 36 + 13.5, 15, INK, TextNode.ALeft, L_BAR_TXT)
        self.typing: Optional[dict] = None

    def _set_title(self, name: str) -> None:
        for n in ([self.title] if self.title else []) + self.title_decor:
            n.removeNode()
        cx = CHAT_X + CHAT_W / 2
        self.title, tn = self._center_text(self.win, name, cx, 25, 15, INK, TextNode.ACenter, L_BAR_TXT)
        half = tn.getWidth() * 15 / 2
        x = cx + half + 12
        self.title_decor = [_lines(self.win, [(x, 22), (x + 4.5, 27), (x + 9, 22)], (0.35, 0.35, 0.35, 1), 1.3, L_BAR_TXT)]

    # ------------------------------------------------------------------ cursor
    def _build_cursor(self) -> None:
        self.cursor = self.win.attachNewNode("cursor")
        tris = [((0, 0), (0, 17), (4.2, 13.2)), ((0, 0), (4.2, 13.2), (6.6, 12.3)), ((0, 0), (6.6, 12.3), (11.8, 12.3)),
                ((4.2, 13.2), (7, 19.5), (9.4, 18.5)), ((4.2, 13.2), (9.4, 18.5), (6.6, 12.3))]
        for dx, dy in ((-1.3, 0), (1.3, 0), (0, -1.3), (0, 1.3), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            _poly(self.cursor, None, (0, 0, 0, 1), L_CURSOR,
                  tris=[tuple((p[0] + dx, p[1] + dy) for p in t) for t in tris])
        _poly(self.cursor, None, WHITE, L_CURSOR + 1, tris=tris)
        self.set_cursor(*self.cursor_xy)

    def set_cursor(self, x: float, y: float) -> None:
        self.cursor_xy = (x, y)
        self.cursor.setPos(x, 0, -y)

    # ------------------------------------------------------------------ state
    def row_center(self, name: str) -> tuple[float, float]:
        return NAV_W + 110.0, self.rows[name]["y"] + ROW_H / 2 + 2

    def _paint_rows(self) -> None:
        cx, cy = self.cursor_xy if hasattr(self, "cursor") else (-1, -1)
        for name, r in self.rows.items():
            col = r["base"]
            if name == self.selected:
                col = LIST_SEL
            elif name == self.pressed:
                col = LIST_SEL
            elif NAV_W <= cx <= NAV_W + LIST_W and r["y"] <= cy < r["y"] + ROW_H:
                col = LIST_HOVER
            r["bg"].setColor(*col)

    def open_chat(self, name: str) -> None:
        self.chats[self.active].root.hide()
        self.active = name
        self.selected = name
        self.chats[name].root.show()
        self._set_title(name)
        for n in self.rows[name]["badge"]:
            n.removeNode()                      # reading it clears the unread badge
        self.rows[name]["badge"] = []

    def play(self, chat: str, item) -> None:
        _, kind, side, payload = item
        c = self.chats[chat]
        if kind == "typesend":
            self.start_typing(chat, side, payload)
        elif kind == "stamp":
            c.add_stamp(payload)
        elif kind == "text":
            c.add_text(side, payload)
        else:
            c.add_image(side, payload)

    def load(self, chat: str, script) -> None:
        """Fill a chat with a conversation that has already happened."""
        for item in script:
            self.play(chat, item)
        self.chats[chat].settle()

    # ------------------------------------------------------------------ typing + clicking Send
    TYPE_START, TYPE_PER_CHAR, TYPE_PAUSE, MOVE_TIME, CLICK_TIME = 0.4, 0.3, 0.4, 0.7, 0.18

    @classmethod
    def type_duration(cls, text: str) -> float:
        return cls.TYPE_START + cls.TYPE_PER_CHAR * len(text) + cls.TYPE_PAUSE + cls.MOVE_TIME + cls.CLICK_TIME

    def start_typing(self, chat: str, side: str, text: str) -> None:
        self.typing = {"chat": chat, "side": side, "text": text, "t": 0.0, "from": self.cursor_xy, "shown": -1}

    def _update_typing(self, dt: float) -> None:
        ty = self.typing
        if ty is None:
            return
        ty["t"] += dt
        t, text = ty["t"], ty["text"]
        t_typed = self.TYPE_START + self.TYPE_PER_CHAR * len(text)
        t_move = t_typed + self.TYPE_PAUSE
        t_click = t_move + self.MOVE_TIME
        t_send = t_click + self.CLICK_TIME

        n = 0 if t < self.TYPE_START else min(len(text), int((t - self.TYPE_START) / self.TYPE_PER_CHAR) + 1)
        if n != ty["shown"]:
            ty["shown"] = n
            self.input_tn.setText(text[:n])
            self.caret.setX(CHAT_X + 14 + self.input_tn.getWidth() * 15 + 1.5)
        if n > 0:
            self.send_bg.setColor(*(SEND_PRESSED if t >= t_click else SEND_READY))
            self.send_tn.setTextColor(1, 1, 1, 1)

        if t >= t_move:                                             # mouse heads for the Send button
            e = _smooth((t - t_move) / self.MOVE_TIME)
            fx, fy = ty["from"]
            tx, tyy = self.send_xy
            self.set_cursor(fx + (tx - fx) * e, fy + (tyy - fy) * e - math.sin(math.pi * e) * 25.0)

        if t >= t_send:                                             # sent: message appears, box clears
            self.input_tn.setText("")
            self.caret.setX(CHAT_X + 14)
            self.send_bg.setColor(*SEND_IDLE)
            self.send_tn.setTextColor(0.32, 0.32, 0.32, 1)
            c = self.chats[ty["chat"]]
            c.add_text(ty["side"], text)
            self.typing = None

    def layout(self) -> None:
        ar = self.app.getAspectRatio()
        s = 2.0 / CANVAS_H
        k = min(1.0, ar / (1280.0 / 720.0))
        self.ui.setScale(s * k / ar, 1, s * k)

    def update(self, dt: float) -> None:
        self.t += dt
        self.layout()
        self._update_typing(dt)
        for c in self.chats.values():
            c.update(dt)
        c = self.chats[self.active]
        c.root.setZ(-HEAD_H + c.scroll)
        if self.t % 1.0 < 0.5:
            self.caret.show()
        else:
            self.caret.hide()
        self._paint_rows()

    def show(self) -> None:
        self.ui.show()

    def hide(self) -> None:
        self.ui.hide()


# ============================================================================================ the cut scene
class Cutscene:
    """Owns the alert, the interaction prompt and the whole fade / freeze / WeChat sequence."""

    DUR = {"fade_out": 0.9, "hold_in": 0.6, "fade_in": 0.9, "chat": 2.0, "bp": 0.05, "cursor": 1.5, "hover": 0.45, "click": 0.22,
           "bp_hold": 5.0, "end_out": 0.9, "hold_out": 0.6, "end_in": 0.9}
    ORDER = ["fade_out", "hold_in", "fade_in", "chat", "cursor", "hover", "click", "bp", "bp_hold",
             "end_out", "hold_out", "end_in"]

    def __init__(self, app, world, player) -> None:
        _ensure_bin()
        self.app, self.world, self.player = app, world, player
        app.input_locked = False

        self.alert = MonitorAlert(app)
        self.wechat = WeChatUI(app)
        self.state = "idle"             # idle -> ready -> playing -> done
        self.clock = 0.0
        self.active = False

        cm = CardMaker("fade")
        cm.setFrame(-1, 1, -1, 1)
        self.fade = app.render2d.attachNewNode(cm.generate())
        self.fade.setColor(0, 0, 0, 0)
        self.fade.setTransparency(TransparencyAttrib.MAlpha)
        _style(self.fade, L_FADE)
        self.fade.hide()

        self.prompt = OnscreenText(text="", parent=app.aspect2d, pos=(0.0, -0.80), scale=0.055, fg=(1, 1, 1, 1),
                                   shadow=(0, 0, 0, 0.9), mayChange=True)
        player.interact_hook = self._try_interact

        self._bg = None
        self._phase_i = 0
        self._switched = False
        self._phase_t = 0.0
        self._switched = False
        self._events: list = []
        self._ev_i = 0
        self._cursor_from = (0.0, 0.0)

    # ------------------------------------------------------------------ interaction
    def _near(self) -> bool:
        p = self.player.agent_position
        return math.hypot(p.x - self.alert.xy[0], p.y - self.alert.xy[1]) <= INTERACT_REACH

    def _try_interact(self) -> bool:
        if self.state == "ready" and self._near():
            self._start()
            return True
        return False

    def _start(self) -> None:
        self.state = "playing"
        self.active = True
        self.app.input_locked = True
        pl = self.player
        pl._movement_vector = None
        pl.speed = 0.0
        pl.local_velocity = Vec3(0, 0, 0)
        self.prompt.setText("")
        self._phase_i, self._phase_t = -1, 0.0
        self._next_phase()

    # ------------------------------------------------------------------ per frame
    def update(self, dt: float) -> None:
        if self.state in ("idle", "ready"):
            self.clock += dt
            if self.state == "idle" and self.clock >= ALERT_DELAY:
                self.alert.show()
                self.state = "ready"
            if self.state == "ready":
                self.alert.update(dt)
                self.prompt.setText("E / Triangle: check monitor" if self._near() else "")
            return
        if self.state == "playing":
            self._tick(dt)

    # ------------------------------------------------------------------ phases
    def _phase_name(self) -> str:
        return self.ORDER[self._phase_i]

    def _next_phase(self) -> None:
        self._phase_i += 1
        self._phase_t = 0.0
        if self._phase_i >= len(self.ORDER):
            self._finish()
            return
        name = self._phase_name()
        self._switched = False
        if name == "cursor":
            self._cursor_from = self.wechat.cursor_xy
        elif name == "click":
            self.wechat.pressed = "BP"
        elif name == "bp":
            self.wechat.pressed = None
            self.wechat.open_chat("BP")
            self.wechat.load("BP", BP_HISTORY)      # the first three messages were already sent
            self._events = self._schedule("BP", BP_LIVE, 0.0, tail=0.0)

    def _schedule(self, chat: str, script, lead: float, tail: float = 1.0):
        t, out = lead, []
        for item in script:
            t += item[0]
            out.append((t, chat, item))
            if item[1] == "typesend":
                t += WeChatUI.type_duration(item[3])        # next message waits until this one is sent
        self._ev_i = 0
        self._end_t = t + tail
        return out

    def _duration(self, name: str) -> float:
        if name == "bp":
            return max(self._end_t, 0.05)
        return self.DUR[name]

    def _tick(self, dt: float) -> None:
        self._phase_t += dt
        name = self._phase_name()
        p = self._phase_t / max(1e-6, self._duration(name))
        w = self.wechat

        # swap scenes only after a few fully black frames have been presented (never mid-fade)
        if name in ("hold_in", "hold_out") and not self._switched and self._phase_t >= 0.2:
            self._switched = True
            self._enter_ui() if name == "hold_in" else self._exit_ui()

        if name in ("fade_out", "end_out"):
            self._set_fade(_smooth(p))
        elif name in ("hold_in", "hold_out"):
            self._set_fade(1.0)
        elif name in ("fade_in", "end_in"):
            self._set_fade(1.0 - _smooth(p))

        if name in ("chat", "bp"):
            while self._ev_i < len(self._events) and self._phase_t >= self._events[self._ev_i][0]:
                _, chat, item = self._events[self._ev_i]
                w.play(chat, item)
                self._ev_i += 1
        elif name == "cursor":
            tx, ty = w.row_center("BP")
            e = _smooth(p)
            fx, fy = self._cursor_from
            arc = math.sin(math.pi * e) * 35.0                        # a slightly human, curved path
            w.set_cursor(fx + (tx - fx) * e, fy + (ty - fy) * e - arc)

        if not w.ui.isHidden():
            w.update(dt)

        if self._phase_t >= self._duration(name):
            self._next_phase()

    def _set_fade(self, a: float) -> None:
        if a <= 0.001:
            self.fade.hide()
        else:
            self.fade.show()
            self.fade.setColor(0, 0, 0, a)

    # ------------------------------------------------------------------ scene switching
    def _enter_ui(self) -> None:
        app = self.app
        self._set_fade(1.0)
        self._bg = app.getBackgroundColor()
        app.setBackgroundColor(0, 0, 0, 1)
        app.render.hide()                   # city, apartment, props, minions: not rendered at all
        app.cam.node().setActive(False)     # ...and the 3D camera does not draw anything either
        app.aspect2d.hide()                 # HUD prompts
        self.wechat.load("Klesa", KLESA_SCRIPT)   # the conversation was already had
        self.wechat.show()
        self.wechat.update(0.0)

    def _exit_ui(self) -> None:
        app = self.app
        self._set_fade(1.0)
        self.wechat.hide()
        app.cam.node().setActive(True)
        app.render.show()
        app.aspect2d.show()
        if self._bg is not None:
            app.setBackgroundColor(self._bg)

    def _finish(self) -> None:
        self.state = "done"
        self.active = False
        self.app.input_locked = False
        self._set_fade(0.0)
        self.alert.destroy()
        self.prompt.setText("")
        self.player.interact_hook = None
