from __future__ import annotations

import math
import random

from panda3d.core import TextNode, TransparencyAttrib

from src.layout import Box
from src.mathutil import dir_from_yaw, yaw_from_dir
from src.meshes import make_box


# ---------------------------------------------------------------- tunables
# (also adjustable live, e.g. game.gun.bullet_speed = 15.0)
BULLET_SPEED = 40.0       # metres / second (player walks 5, minions 3.6)
BULLET_DAMAGE = 2.0       # minion hp is 5 (see MINION_HP in minion.py) -> 3 hits
MAG_SIZE = 7
RELOAD_TIME = 3.0         # seconds
FIRE_COOLDOWN = 0.15      # minimum seconds between shots
AIM_RANGE = 25.0          # auto-aim only picks minions within this distance
BULLET_RANGE = 30.0       # bullets vanish after travelling this far
AIM_REQUIRES_LOS = True   # skip minions hidden behind walls / closed doors
BULLET_RADIUS = 0.06
MUZZLE_HEIGHT = 1.1

COL_GUN = (0.12, 0.12, 0.14, 1.0)
COL_BULLET = (1.0, 0.9, 0.3, 1.0)

C_BANG = (1.0, 0.9, 0.3, 1.0)
C_HIT = (1.0, 0.55, 0.2, 1.0)
C_KILL = (1.0, 0.2, 0.2, 1.0)
C_WALL = (0.8, 0.8, 0.8, 1.0)
C_RELOAD = (0.5, 0.9, 1.0, 1.0)


def _seg_circle_t(ax, ay, bx, by, cx, cy, r):
    """Parameter t (0..1) of the closest point on segment a->b if it passes within r of c."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / l2))
    px, py = ax + dx * t, ay + dy * t
    if (px - cx) ** 2 + (py - cy) ** 2 <= r * r:
        return t
    return None


class FloatingText:
    """Comic-book 'sound effect' words that rise and fade in the world."""

    def __init__(self, app) -> None:
        self.app = app
        self._pops: list[list] = []

    def spawn(self, text: str, x: float, y: float, z: float, colour=(1, 1, 1, 1),
              scale: float = 0.5, life: float = 0.7, rise: float = 1.2) -> None:
        tn = TextNode("sfx")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(*colour)
        tn.setShadow(0.05, 0.05)
        tn.setShadowColor(0, 0, 0, 0.9)
        np = self.app.render.attachNewNode(tn)
        np.setScale(scale)
        np.setPos(x + random.uniform(-0.25, 0.25), y, z)
        np.setBillboardPointEye()
        np.setLightOff()
        np.setTransparency(TransparencyAttrib.MAlpha)
        np.setDepthTest(False)
        np.setDepthWrite(False)
        np.setBin("fixed", 60)
        self._pops.append([np, 0.0, life, rise])

    def update(self, dt: float) -> None:
        keep = []
        for pop in self._pops:
            np, age, life, rise = pop
            age += dt
            if age >= life:
                np.removeNode()
                continue
            pop[1] = age
            np.setZ(np.getZ() + rise * dt)
            fade = 1.0 - max(0.0, (age / life - 0.5) * 2.0)
            np.setColorScale(1, 1, 1, fade)
            keep.append(pop)
        self._pops = keep


class _Bullet:
    def __init__(self, node, x: float, y: float, ux: float, uy: float) -> None:
        self.node = node
        self.x, self.y = x, y
        self.ux, self.uy = ux, uy
        self.travelled = 0.0


class Gun:
    def __init__(self, app, world, player, swarm) -> None:
        self.app = app
        self.world = world
        self.player = player
        self.swarm = swarm

        self.bullet_speed = BULLET_SPEED
        self.damage = BULLET_DAMAGE
        self.mag_size = MAG_SIZE
        self.reload_time = RELOAD_TIME
        self.fire_cooldown = FIRE_COOLDOWN
        self.aim_range = AIM_RANGE
        self.bullet_range = BULLET_RANGE
        self.aim_requires_los = AIM_REQUIRES_LOS

        self.ammo = self.mag_size
        self.reload_left = 0.0
        self.cooldown = 0.0
        self.kills = 0

        self.fx = FloatingText(app)
        self.bullets: list[_Bullet] = []
        self._aim = (0.0, 1.0)
        self._retarget_timer = 0.0
        self._clack_done = False

        self.gun_root = app.render.attachNewNode("gun")
        make_box("gun-body", Box(-0.05, 0.0, 0.05, 0.55, -0.07, 0.07), COL_GUN, self.gun_root)
        make_box("gun-grip", Box(-0.04, 0.05, 0.04, 0.17, -0.20, -0.07), COL_GUN, self.gun_root)

        self.hud = None
        self._hud_text = None
        parent = getattr(app, "a2dBottomRight", None)
        if parent is not None:
            from direct.gui.OnscreenText import OnscreenText
            self.hud = OnscreenText(
                text="", parent=parent, pos=(-0.08, 0.08), scale=0.07, fg=(1.0, 0.9, 0.4, 1),
                shadow=(0, 0, 0, 0.9), align=TextNode.ARight, mayChange=True)

        pad = getattr(player, "gamepad", None)
        if pad is not None:
            pad.on_shoot = self.shoot       # Square
            pad.on_reload = self.reload     # R1

    # ------------------------------------------------------------ aiming
    @property
    def reload_progress(self) -> float:
        if self.reload_left <= 0.0:
            return 0.0
        return 1.0 - self.reload_left / max(1e-3, self.reload_time)

    def _line_clear(self, x: float, y: float, m) -> bool:
        p = m.position
        ex, ey = self.world.collision.sweep(x, y, p.x, p.y, 0.05, step=0.15)
        return math.hypot(ex - p.x, ey - p.y) < 0.1

    def _pick_target(self):
        pl = self.player.agent_position
        cands = []
        for m in self.swarm.alive():
            p = m.position
            d = math.hypot(p.x - pl.x, p.y - pl.y)
            if d <= self.aim_range:
                cands.append((d, m))
        cands.sort(key=lambda c: c[0])
        for _, m in cands:
            if not self.aim_requires_los or self._line_clear(pl.x, pl.y, m):
                return m
        return None

    def _aim_at(self, m) -> None:
        pl = self.player.agent_position
        p = m.position
        dx, dy = p.x - pl.x, p.y - pl.y
        d = math.hypot(dx, dy) or 1.0
        self._aim = (dx / d, dy / d)

    def _refresh_aim(self) -> None:
        t = self._pick_target()
        if t is not None:
            self._aim_at(t)
        else:
            self._aim_along_movement()

    def _aim_along_movement(self) -> None:
        mv = self.player._movement_vector
        if mv is not None and (mv.x * mv.x + mv.y * mv.y) > 1e-6:
            n = math.hypot(mv.x, mv.y)
            self._aim = (mv.x / n, mv.y / n)
        else:                               # standing still: last facing direction
            d = dir_from_yaw(self.player.body_yaw)
            self._aim = (d.x, d.y)

    # ------------------------------------------------------------ actions
    def _say_at_player(self, text: str, colour=C_BANG, scale: float = 0.5, life: float = 0.7) -> None:
        pl = self.player.agent_position
        self.fx.spawn(text, pl.x, pl.y, 2.3, colour, scale, life)

    def shoot(self) -> None:
        if self.reload_left > 0.0:
            return
        if self.cooldown > 0.0:
            return
        if self.ammo <= 0:
            self.cooldown = 0.25
            self._say_at_player("No Ammo!", C_WALL, 0.4, 0.8)
            return

        target = self._pick_target()
        if target is not None:
            self._aim_at(target)
        else:
            self._aim_along_movement()      # no target: fire the way the player is moving

        pl = self.player.agent_position
        ux, uy = self._aim
        node = make_box("bullet", Box(-0.04, -0.2, 0.04, 0.2, -0.04, 0.04), COL_BULLET, self.app.render)
        node.setLightOff()
        node.setPos(pl.x, pl.y, MUZZLE_HEIGHT)
        node.setH(-yaw_from_dir(ux, uy))
        self.bullets.append(_Bullet(node, pl.x, pl.y, ux, uy))

        self.ammo -= 1
        self.cooldown = self.fire_cooldown
        self.fx.spawn('FAH!', pl.x + ux * 0.8, pl.y + uy * 0.8, 1.9, C_BANG, 0.55, 0.5)
        if self.ammo == 0:
            self._say_at_player("No Ammo!", C_WALL, 0.4, 0.9)

    def reload(self) -> None:
        if self.reload_left > 0.0 or self.ammo >= self.mag_size:
            return
        self.reload_left = self.reload_time
        self._clack_done = False
        self._say_at_player("reloading...", C_RELOAD, 0.45, 1.0)

    def _tick_reload(self, dt: float) -> None:
        total = max(1e-3, self.reload_time)
        self.reload_left = max(0.0, self.reload_left - dt)
        if not self._clack_done and self.reload_left <= total * 0.5:
            self._clack_done = True
            self._say_at_player("reloading...", C_RELOAD, 0.45, 1.0)
        if self.reload_left <= 0.0:
            self.ammo = self.mag_size
            self._say_at_player("Reloaded!", C_RELOAD, 0.45, 0.9)

    # ------------------------------------------------------------ bullets
    def _hit_minion(self, m) -> None:
        p = m.position                      # read before kill() removes the node
        x, y = p.x, p.y
        if m.take_damage(self.damage):
            self.kills += 1
            self.fx.spawn("Dead!", x, y, 1.9, C_KILL, 0.45, 0.8)
        else:
            self.fx.spawn("Hit!", x, y, 1.9, C_HIT, 0.45, 0.5)

    def _update_bullets(self, dt: float) -> None:
        col = self.world.collision
        minions = self.swarm.alive()
        keep = []
        for b in self.bullets:
            step = min(self.bullet_speed * dt, self.bullet_range - b.travelled)
            ax, ay = b.x, b.y
            bx, by = ax + b.ux * step, ay + b.uy * step
            ex, ey = col.sweep(ax, ay, bx, by, BULLET_RADIUS, step=0.1)
            wall = math.hypot(ex - bx, ey - by) > 1e-6

            best = None
            for m in minions:
                if not m.alive:
                    continue
                p = m.position
                t = _seg_circle_t(ax, ay, ex, ey, p.x, p.y, m.radius + BULLET_RADIUS)
                if t is not None and (best is None or t < best[0]):
                    best = (t, m)

            if best is not None:
                self._hit_minion(best[1])
                b.node.removeNode()
                continue
            if wall:
                self.fx.spawn("tink", ex, ey, 1.3, C_WALL, 0.35, 0.4)
                b.node.removeNode()
                continue

            b.x, b.y = bx, by
            b.travelled += step
            if b.travelled >= self.bullet_range - 1e-6:
                b.node.removeNode()
                continue
            b.node.setPos(b.x, b.y, MUZZLE_HEIGHT)
            keep.append(b)
        self.bullets = keep

    # ------------------------------------------------------------ visuals
    def _update_model(self) -> None:
        pl = self.player.agent_position
        ux, uy = self._aim
        pitch = 0.0
        if self.reload_left > 0.0:
            p = self.reload_progress
            edge = 0.12
            f = max(0.0, min(1.0, p / edge, (1.0 - p) / edge))
            f = f * f * (3.0 - 2.0 * f)
            pitch = -70.0 * f + math.sin(p * 60.0) * 6.0 * f
        self.gun_root.setPos(pl.x + ux * 0.35, pl.y + uy * 0.35, MUZZLE_HEIGHT)
        self.gun_root.setHpr(-yaw_from_dir(ux, uy), pitch, 0.0)

    def _update_hud(self) -> None:
        if self.hud is None:
            return
        if self.reload_left > 0.0:
            n = int(self.reload_progress * 10)
            text = f"Reloading [{'#' * n}{'-' * (10 - n)}] {self.reload_left:.1f}s"
        else:
            text = f"Ammo {self.ammo} / {self.mag_size}"
        if text != self._hud_text:
            self._hud_text = text
            self.hud.setText(text)

    def update(self, dt: float) -> None:
        if dt <= 0.0:
            return
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.reload_left > 0.0:
            self._tick_reload(dt)

        self._retarget_timer -= dt
        if self._retarget_timer <= 0.0:
            self._retarget_timer = 0.1
            self._refresh_aim()

        self._update_bullets(dt)
        self.fx.update(dt)
        self._update_model()
        self._update_hud()
