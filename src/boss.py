from __future__ import annotations

import math
import os
from typing import Optional

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    CardMaker, Filename, Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
    Material, NodePath, TextNode, TransparencyAttrib, Vec3, Vec4,
)

from src import layout
from src.city import DROP
from src.destruction import OBB
from src.player import make_capsule


def _smoothstep(p: float) -> float:
    p = max(0.0, min(1.0, p))
    return p * p * (3.0 - 2.0 * p)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _material(diffuse, ambient, shininess: float = 34.0) -> Material:
    m = Material()
    m.setDiffuse(Vec4(*diffuse, 1.0))
    m.setAmbient(Vec4(*ambient, 1.0))
    m.setSpecular(Vec4(0.55, 0.30, 0.65, 1.0))
    m.setShininess(shininess)
    return m


# ------------------------------------------------------------------------------------------------ geometry helpers
def make_tube(radius: float, segments: int = 24) -> GeomNode:
    """Open cylinder of length 1 along +Y (scale its Y to set the length)."""
    vdata = GeomVertexData("tube", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vw, nw = GeomVertexWriter(vdata, "vertex"), GeomVertexWriter(vdata, "normal")
    for y in (0.0, 1.0):
        for j in range(segments):
            a = 2.0 * math.pi * j / segments
            c, s = math.cos(a), math.sin(a)
            vw.addData3(radius * c, y, radius * s)
            nw.addData3(c, 0.0, s)
    prim = GeomTriangles(Geom.UHStatic)
    for j in range(segments):
        jn = (j + 1) % segments
        prim.addVertices(j, segments + jn, segments + j)
        prim.addVertices(j, jn, segments + jn)
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode("tube")
    node.addGeom(geom)
    return node


def _flat_quad(parent: NodePath, corners, z: float, rgba, name: str = "decal") -> NodePath:
    vdata = GeomVertexData(name, GeomVertexFormat.getV3c4(), Geom.UHStatic)
    vw, cw = GeomVertexWriter(vdata, "vertex"), GeomVertexWriter(vdata, "color")
    for x, y in corners:
        vw.addData3(x, y, z)
        cw.addData4(*rgba)
    prim = GeomTriangles(Geom.UHStatic)
    prim.addVertices(0, 1, 2)
    prim.addVertices(0, 2, 3)
    geom = Geom(vdata)
    geom.addPrimitive(prim)
    node = GeomNode(name)
    node.addGeom(geom)
    np = parent.attachNewNode(node)
    np.setLightOff()
    np.setTwoSided(True)
    np.setTransparency(TransparencyAttrib.MAlpha)
    return np


def _segment(parent: NodePath, a: Vec3, b: Vec3, radius: float, material: Material, segments: int = 14) -> NodePath:
    """A capsule from a to b (both tips included), used for fingers."""
    length = (b - a).length()
    holder = parent.attachNewNode("seg")
    holder.setPos(a)
    holder.lookAt(parent, b)                              # +Y of the holder now points at b
    cap = holder.attachNewNode(make_capsule(radius, length + 2.0 * radius, segments=segments, cap_rings=4))
    cap.setP(-90)                                         # capsule axis (+Z) -> +Y
    cap.setY(-radius)
    cap.setMaterial(material, 1)
    cap.setTwoSided(True)
    return holder


# ------------------------------------------------------------------------------------------------ dialogue text
BOLD_FONTS = (
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


class BossSpeech:
    """Big bold red lines across the middle of the screen."""

    def __init__(self, app) -> None:
        self.app = app
        self.font, self.fake_bold = None, True
        for p in BOLD_FONTS:
            if os.path.exists(p):
                f = app.loader.loadFont(Filename.fromOsSpecific(p).getFullpath())
                if f is not None and f.isValid():
                    f.setPixelsPerUnit(96)
                    self.font, self.fake_bold = f, "Bold" not in p and "bd" not in p
                    break
        self.layers: list[OnscreenText] = []
        offsets = [(0.0, 0.0)]
        if self.fake_bold:                                   # no bold face available: thicken by overdrawing
            offsets = [(dx, dz) for dx in (-0.004, 0.0, 0.004) for dz in (-0.004, 0.0, 0.004)]
        for dx, dz in offsets:
            t = OnscreenText(text="", parent=app.aspect2d, pos=(dx, 0.12 + dz), scale=0.16,
                             fg=(0.95, 0.04, 0.04, 1), shadow=(0, 0, 0, 1), font=self.font, align=TextNode.ACenter,
                             mayChange=True)
            t.setBin("fixed", 90)
            self.layers.append(t)
        self.time = 0.0
        self.total = 0.0

    def say(self, text: str, seconds: float) -> None:
        for t in self.layers:
            t.setText(text)
            t.show()
        self.time, self.total = 0.0, seconds

    def clear(self) -> None:
        self.total = 0.0
        for t in self.layers:
            t.setText("")

    def update(self, dt: float) -> None:
        if self.total <= 0.0:
            return
        self.time += dt
        if self.time >= self.total:
            self.clear()
            return
        a = min(1.0, self.time / 0.15, (self.total - self.time) / 0.4)
        for t in self.layers:
            t.setAlphaScale(max(0.0, a))


# ------------------------------------------------------------------------------------------------ hand + arm
class BossArm:
    HAND_BACK, HAND_FRONT, HAND_HALF_W = 1.9, 4.2, 2.3       # footprint of the palm + fingers around the hand origin
    ARM_HALF_W = 1.4
    PALM_Z = 0.8                                             # palm centre height when it is pressed onto the floor

    def __init__(self, app, material: Material) -> None:
        self.root = app.render.attachNewNode("boss-arm")
        self.material = material

        self.hand = self.root.attachNewNode("boss-hand")
        palm = self.hand.attachNewNode("palm")
        palm.setScale(1.8, 1.9, 0.8)
        ball = palm.attachNewNode(make_capsule(1.0, 2.0, segments=28, cap_rings=10))
        ball.setZ(-1.0)
        ball.setMaterial(material, 1)
        ball.setTwoSided(True)
        for x in (-1.2, -0.4, 0.4, 1.2):                     # four fingers, slightly splayed
            _segment(self.hand, Vec3(x, 1.2, 0.0), Vec3(x * 1.18, 3.5, 0.0), 0.38, material)
        _segment(self.hand, Vec3(1.4, -0.3, 0.0), Vec3(2.7, 1.1, 0.0), 0.46, material)    # thumb

        self.arm = self.root.attachNewNode("forearm")
        tube = self.arm.attachNewNode(make_tube(self.ARM_HALF_W))
        tube.setMaterial(material, 1)
        tube.setTwoSided(True)
        self.shoulder = self.root.attachNewNode("shoulder")
        s = self.shoulder.attachNewNode(make_capsule(self.ARM_HALF_W, 2.0 * self.ARM_HALF_W, segments=20, cap_rings=8))
        s.setZ(-self.ARM_HALF_W)
        s.setMaterial(material, 1)
        self.root.hide()

    def pose(self, hand: Vec3, ux: float, uy: float, shoulder: Vec3) -> None:
        """Hand origin at `hand`, fingers pointing along (ux, uy); the forearm runs from the shoulder to the wrist."""
        self.hand.setPos(hand)
        self.hand.lookAt(hand + Vec3(ux, uy, 0.0))
        wrist = hand - Vec3(ux, uy, 0.0) * 1.5
        d = wrist - shoulder
        self.arm.setPos(shoulder)
        self.arm.lookAt(wrist)
        self.arm.setSy(max(0.01, d.length()))
        self.shoulder.setPos(shoulder)

    def show(self) -> None:
        self.root.show()

    def hide(self) -> None:
        self.root.hide()


class SlamIndicator:
    """Red floor markings showing where the hand and arm are about to land (drawn on top of the walls)."""

    def __init__(self, app) -> None:
        self.root = app.render.attachNewNode("slam-indicator")
        self.root.setDepthTest(False)
        self.root.setDepthWrite(False)
        self.root.setBin("fixed", 45)
        self.fill: Optional[NodePath] = None
        self.base: Optional[NodePath] = None
        self.root.hide()

    def build(self, hand: OBB, arm: Optional[OBB]) -> None:
        self.clear()
        self.base = self.root.attachNewNode("base")
        self.fill = self.root.attachNewNode("fill")
        for obb in [o for o in (arm, hand) if o is not None]:
            c = obb.corners()
            _flat_quad(self.base, c, 0.14, (0.55, 0.02, 0.02, 0.40))
            _flat_quad(self.fill, c, 0.16, (1.0, 0.12, 0.05, 1.0))
            # bright border so the edge reads clearly
            for (a, b) in zip(c, c[1:] + c[:1]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                n = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / n * 0.11, dx / n * 0.11
                _flat_quad(self.base, [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                                       (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)], 0.18, (1.0, 0.25, 0.1, 0.95))
        self.root.show()

    def set_progress(self, p: float) -> None:
        """0 -> 1 over the warning time: the fill gets stronger and flashes right before the hit."""
        if self.fill is None:
            return
        a = 0.10 + 0.50 * p
        if p > 0.82 and int(p * 60) % 2 == 0:
            a = 0.85
        self.fill.setColorScale(1, 1, 1, a)

    def clear(self) -> None:
        for n in (self.base, self.fill):
            if n is not None:
                n.removeNode()
        self.base = self.fill = None
        self.root.hide()


# ------------------------------------------------------------------------------------------------ capture bar
class CaptureBar:
    """Bar over Anna's head that fills while minions are on her."""
    WIDTH = 2.8

    def __init__(self, anna) -> None:
        self.root = anna.tag_root.attachNewNode("capture-bar")
        self.root.setZ(3.5)
        self.root.setBillboardPointEye()
        self.root.setLightOff()
        self.root.setDepthTest(False)
        self.root.setDepthWrite(False)
        self.root.setBin("fixed", 62)
        cm = CardMaker("bar")
        cm.setFrame(0.0, 1.0, -0.5, 0.5)
        back = self.root.attachNewNode(cm.generate())
        back.setScale(self.WIDTH + 0.2, 1, 0.55)
        back.setX(-(self.WIDTH + 0.2) / 2)
        back.setColor(0, 0, 0, 0.85)
        self.fill = self.root.attachNewNode(cm.generate())
        self.fill.setPos(-self.WIDTH / 2, -0.01, 0.0)
        self.fill.setColor(0.95, 0.10, 0.10, 1)
        self.fill.setScale(0.001, 1, 0.38)
        self.root.hide()

    def set(self, value: float) -> None:
        if value <= 0.005:
            self.root.hide()
            return
        self.root.show()
        self.fill.setSx(max(0.001, min(1.0, value)) * self.WIDTH)

    def destroy(self) -> None:
        self.root.removeNode()


# ------------------------------------------------------------------------------------------------ attacks
class Attack1:
    """The hand slams down on Anna, three times."""
    SLAMS = 3
    TELEGRAPH = 2.0        # seconds the player gets to dodge
    TRAVEL = 0.9           # the hand flies to its hover point during the first part of the warning
    SLAM_TIME = 0.16
    HOLD = 0.9
    RETREAT = 0.8
    GAP = 0.45
    HOVER_Z, REST_Z = 16.0, 20.0

    def __init__(self, boss: "Boss") -> None:
        self.boss = boss
        self.count = 0
        self.state = "begin"
        self.t = 0.0
        self.hand_pos = Vec3(0, 0, 0)

    def _begin_slam(self) -> None:
        b = self.boss
        a = b.anna.position
        tx, ty = a.x, a.y
        ux, uy = tx - b.pos.x, ty - b.pos.y
        n = math.hypot(ux, uy) or 1.0
        self.ux, self.uy = ux / n, uy / n
        self.target = (tx, ty)
        self.shoulder = Vec3(b.pos.x + self.ux * 8.0, b.pos.y + self.uy * 8.0, 2.5)
        self.rest = Vec3(b.pos.x + self.ux * 12.0, b.pos.y + self.uy * 12.0, self.REST_Z)
        self.hover = Vec3(tx, ty, self.HOVER_Z)

        self.hand_obb = OBB(tx, ty, self.ux, self.uy, -BossArm.HAND_BACK, BossArm.HAND_FRONT, BossArm.HAND_HALF_W)
        reach = math.hypot(tx - self.shoulder.x, ty - self.shoulder.y)
        self.arm_obb = OBB(tx, ty, self.ux, self.uy, -reach, -BossArm.HAND_BACK + 0.8, BossArm.ARM_HALF_W)

        # the part of the arm that is over the apartment is what the indicator shows
        ycut = layout.balcony_box().y1 + 1.5
        arm_vis = None
        if self.uy < -1e-4 and ty < ycut:
            smin = max(-reach, (ycut - ty) / self.uy)
            arm_vis = OBB(tx, ty, self.ux, self.uy, smin, -BossArm.HAND_BACK + 0.8, BossArm.ARM_HALF_W)
        b.indicator.build(self.hand_obb, arm_vis)

        self.hand_pos = Vec3(self.rest)
        b.arm.pose(self.hand_pos, self.ux, self.uy, self.shoulder)
        b.arm.show()
        self.state, self.t = "telegraph", 0.0

    def _impact(self) -> None:
        b = self.boss
        b.indicator.clear()
        source = (self.target[0] - self.ux * 3.0, self.target[1] - self.uy * 3.0)
        b.world.crush([self.hand_obb, self.arm_obb], source)
        b.camera_rig.do_shake(9.0)
        b.add_crush_mark(self.hand_obb)

        a, p = b.anna.position, b.player.agent_position
        if self.hand_obb.hits_circle(a.x, a.y, b.anna.radius) or self.arm_obb.hits_circle(a.x, a.y, b.anna.radius):
            b.game_over("Anna was squished by the boss's hand")
        elif self.hand_obb.hits_circle(p.x, p.y, b.player.radius) or self.arm_obb.hits_circle(p.x, p.y, b.player.radius):
            b.game_over("You were squished by the boss's hand")

    def update(self, dt: float) -> bool:
        b = self.boss
        if self.state == "begin":
            self._begin_slam()
            return False
        self.t += dt

        if self.state == "telegraph":
            e = _smoothstep(self.t / self.TRAVEL)
            bob = math.sin(self.t * 5.0) * 0.4 * e
            self.hand_pos = Vec3(_lerp(self.rest.x, self.hover.x, e), _lerp(self.rest.y, self.hover.y, e),
                                 _lerp(self.rest.z, self.hover.z, e) + bob)
            b.indicator.set_progress(self.t / self.TELEGRAPH)
            if self.t >= self.TELEGRAPH:
                self.state, self.t = "slam", 0.0
        elif self.state == "slam":
            p = min(1.0, self.t / self.SLAM_TIME)
            self.hand_pos = Vec3(self.hover.x, self.hover.y, _lerp(self.HOVER_Z, BossArm.PALM_Z, p * p))
            if p >= 1.0:
                self._impact()
                self.state, self.t = "hold", 0.0
        elif self.state == "hold":
            if self.t >= self.HOLD:
                self.state, self.t = "retreat", 0.0
        elif self.state == "retreat":
            e = _smoothstep(self.t / self.RETREAT)
            self.hand_pos = Vec3(_lerp(self.hover.x, self.rest.x, e), _lerp(self.hover.y, self.rest.y, e),
                                 _lerp(BossArm.PALM_Z, self.REST_Z, e))
            if self.t >= self.RETREAT:
                self.count += 1
                if self.count >= self.SLAMS:
                    b.arm.hide()
                    return True
                self.state, self.t = "gap", 0.0
        elif self.state == "gap":
            if self.t >= self.GAP:
                self._begin_slam()
                return False

        b.arm.pose(self.hand_pos, self.ux, self.uy, self.shoulder)
        return False

    def cleanup(self) -> None:
        self.boss.indicator.clear()
        self.boss.arm.hide()


class Attack2:
    """"Get that fucking DOG": ten minions go for Anna and try to seize her."""
    LINE = "Get that fucking DOG"
    SHOUT_TIME = 1.8
    COUNT = 10
    MAX_TIME = 35.0                 # if the dog is still alive after this long the boss moves on regardless
    CAPTURE_RANGE = 1.0             # minion-to-Anna distance that counts as touching
    SECONDS_ALONE = 5.0             # one minion on her fills the bar in this long (more minions = faster)
    DECAY = 0.6                     # bar drains per second while nobody touches her

    def __init__(self, boss: "Boss") -> None:
        self.boss = boss
        self.state, self.t = "shout", 0.0
        self.bar = 0.0
        boss.speech.say(self.LINE, self.SHOUT_TIME)

    def update(self, dt: float) -> bool:
        b = self.boss
        self.t += dt
        if self.state == "shout":
            if self.t >= self.SHOUT_TIME:
                b.swarm.set_target("anna")
                b.swarm.spawn_group(self.COUNT)
                self.state, self.t = "hunt", 0.0
            return False

        a = b.anna.position
        touching = sum(1 for m in b.swarm.alive()
                       if not m.fleeing and math.hypot(m.position.x - a.x, m.position.y - a.y) <= self.CAPTURE_RANGE)
        if touching:
            self.bar += touching * dt / self.SECONDS_ALONE
        else:
            self.bar = max(0.0, self.bar - self.DECAY * dt)
        b.capture.set(self.bar)
        if self.bar >= 1.0:
            b.game_over("Anna was captured")
            return False

        if b.swarm.alive_count() == 0 or self.t >= self.MAX_TIME:
            self.cleanup()
            return True
        return False

    def cleanup(self) -> None:
        self.boss.capture.set(0.0)
        self.boss.swarm.set_target("player")


# ------------------------------------------------------------------------------------------------ the boss
class Boss:
    # --- tuning (game metres; our floor / the balcony is z = 0, the street is z = -DROP)
    GROW_TIME = 5.0                  # seconds for the whole entrance
    START_DELAY = 0.6                # beat between the cut scene fading back in and the ground starting to shake
    RADIUS = 20.0
    ABOVE_BALCONY = -24.0              # final top height above our floor: just a bit taller than the balcony
    DISTANCE = 34.0                  # from the balcony's north edge to the middle of the boss
    START_SCALE = 0.02               # the pill begins as a speck on the road

    RUMBLE_MIN, RUMBLE_MAX = 1.2, 4.0
    RUMBLE_FADE = 0.35               # seconds for the shake to die away after the top passes the balcony

    QUESTION_DELAY = 2.0             # after the boss is fully out
    QUESTION = "Is that a black dog??"
    QUESTION_TIME = 2.6
    FIRST_ATTACK_DELAY = 0.7         # after the question disappears

    ATTACKS = (Attack1, Attack2)     # cycled in this order; attack 3 comes later

    def __init__(self, app, world, camera_rig, player, anna, swarm) -> None:
        self.app, self.world, self.camera_rig = app, world, camera_rig
        self.player, self.anna, self.swarm = player, anna, swarm
        self.height = DROP + self.ABOVE_BALCONY
        self.base_z = -DROP

        bal = layout.balcony_box()
        self.pos = Vec3((bal.x0 + bal.x1) * 0.5, bal.y1 + self.DISTANCE, self.base_z)

        self.root = app.render.attachNewNode("boss")
        self.root.setPos(self.pos)
        self.model = self.root.attachNewNode(make_capsule(self.RADIUS, self.height, segments=56, cap_rings=18))
        self.model.setTwoSided(True)
        self.model.setMaterial(_material((0.42, 0.10, 0.55), (0.20, 0.05, 0.28)), 1)
        self.root.hide()

        hand_mat = _material((0.50, 0.14, 0.64), (0.24, 0.07, 0.32), 30.0)
        self.arm = BossArm(app, hand_mat)
        self.indicator = SlamIndicator(app)
        self.speech = BossSpeech(app)
        self.capture = CaptureBar(anna)
        self._marks: list[NodePath] = []

        self.mode = "idle"           # idle -> waiting -> growing -> post -> attack | gameover
        self.t = 0.0
        self.scale = 0.0
        self._rumble_done = 0.0
        self._said = False
        self.attack = None
        self._cycle = 0
        self.game_over_reason: Optional[str] = None
        self.on_game_over = None     # optional callback(reason) for the real game-over screen

    # ------------------------------------------------------------------ state
    @property
    def top_z(self) -> float:
        return self.base_z + self.height * self.scale

    def _reset(self) -> None:
        if self.attack is not None:
            self.attack.cleanup()
        self.attack = None
        self.arm.hide()
        self.indicator.clear()
        self.speech.clear()
        self.capture.set(0.0)
        self.swarm.set_target("player")
        self._cycle = 0
        self._said = False
        self.game_over_reason = None

    def start(self, immediate: bool = False) -> None:
        """Begin the entrance (growth + camera rumble). Restarts it if the boss is already out.
        immediate=True skips the short pause before the shaking starts (used by the debug key)."""
        self._reset()
        self.mode, self.t, self._rumble_done = "waiting", 0.0, 0.0
        if immediate:
            self.t = self.START_DELAY
        self.scale = 0.0
        self.camera_rig.set_rumble(0.0)
        self.root.hide()

    def debug_attack(self, which: int) -> None:
        """Debug: put the boss in place at once and start attack `which` (1 or 2) right now."""
        self._reset()
        self.camera_rig.set_rumble(0.0)
        self.scale = 1.0
        self.root.setScale(1.0)
        self.root.show()
        self._cycle = (which - 1) % len(self.ATTACKS)
        self._start_attack()

    # ------------------------------------------------------------------ attacks
    def _start_attack(self) -> None:
        self.attack = self.ATTACKS[self._cycle](self)
        self.mode = "attack"

    def game_over(self, reason: str) -> None:
        """PLACEHOLDER: the real game-over flow comes later. Freezes the boss and shows a banner."""
        if self.mode == "gameover":
            return
        self.mode, self.game_over_reason = "gameover", reason
        self.camera_rig.set_rumble(0.0)
        print(f"[boss] GAME OVER: {reason}")
        self.speech.say(f"GAME OVER\n{reason}", 1e9)
        if self.on_game_over is not None:
            self.on_game_over(reason)

    def add_crush_mark(self, obb: OBB) -> None:
        mark = _flat_quad(self.world.root, obb.corners(), 0.07, (0.0, 0.0, 0.0, 0.40), "crush-mark")
        self._marks.append(mark)
        if len(self._marks) > 12:
            self._marks.pop(0).removeNode()

    # ------------------------------------------------------------------ per frame
    def update(self, dt: float) -> None:
        self.speech.update(dt)
        if self.mode in ("idle", "gameover"):
            return

        self.t += dt
        if self.mode == "waiting":
            if self.t < self.START_DELAY:
                return
            self.mode, self.t = "growing", 0.0
            self.root.show()

        if self.mode == "growing":
            self._grow(dt)
            return

        if self.mode == "post":
            if not self._said and self.t >= self.QUESTION_DELAY:
                self._said = True
                self.speech.say(self.QUESTION, self.QUESTION_TIME)
            if self._said and self.t >= self.QUESTION_DELAY + self.QUESTION_TIME + self.FIRST_ATTACK_DELAY:
                self._start_attack()
            return

        if self.mode == "attack":
            if self.attack.update(dt):
                self._cycle = (self._cycle + 1) % len(self.ATTACKS)
                self._start_attack()

    def _grow(self, dt: float) -> None:
        p = self.t / self.GROW_TIME
        self.scale = self.START_SCALE + (1.0 - self.START_SCALE) * _smoothstep(p)
        self.root.setScale(self.scale)

        # camera rumble: builds as the boss climbs, fades out once its top has reached the balcony
        climbed = max(0.0, min(1.0, (self.top_z - self.base_z) / DROP))
        if climbed < 1.0:
            self.camera_rig.set_rumble(self.RUMBLE_MIN + (self.RUMBLE_MAX - self.RUMBLE_MIN) * climbed)
        else:
            self._rumble_done += dt
            fade = max(0.0, 1.0 - self._rumble_done / self.RUMBLE_FADE)
            self.camera_rig.set_rumble(self.RUMBLE_MAX * fade)
        if p >= 1.0:
            self.scale = 1.0
            self.root.setScale(1.0)
            self.camera_rig.set_rumble(0.0)
            self.mode, self.t = "post", 0.0
            self._said = False
