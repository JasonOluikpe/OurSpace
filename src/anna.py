from __future__ import annotations
 
import math
from typing import Optional
 
from panda3d.core import Material, NodePath, TextNode, Vec3, Vec4
 
from src.mathutil import yaw_from_dir
from src.player import make_capsule
 
BODY_RADIUS = 0.30
BODY_HEIGHT = 0.90            # the player's capsule is 1.8 tall, so Anna is half height
 
 
def _hyp(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)
 
 
class Anna:
    NAME = "Anna"
 
    # --- movement
    radius = BODY_RADIUS
    speed = 6.5                 # faster than the player (5) and the minions (3.6)
    LEASH = 10.0                # hard limit: never further than this from the player
    HEEL = 2.8                  # idle distance from the player
    ENGAGE = 8.0                # only hunts minions within this distance of the player
 
    # --- bite
    BITE_RANGE = 1.15
    BITE_COOLDOWN = 0.7
 
    # --- bark
    BARK_CROWD = 2              # bark when at least this many *scareable* minions are close to her
                                # (minions in a group of 3+ are confident and ignore barking)
    CROWD_RADIUS = 5.0
    BARK_RADIUS = 6.0           # minions inside this radius can be scared...
    BARK_MAX = 4                # ...but only the closest few
    BARK_COOLDOWN = 7.0
    BARK_CHASE = 2.2            # how long she herds the scared minions (no biting)
    BARK_FLEE = 3.0             # how long scared minions run
 
    def __init__(self, app, world, player, swarm) -> None:
        self.app = app
        self.world = world
        self.player = player
        self.swarm = swarm
 
        sx, sy = _spawn_xy()
        self.node = app.render.attachNewNode("anna")
        self.node.setPos(sx, sy, 0.0)
        self.body = self.node.attachNewNode(make_capsule(radius=BODY_RADIUS, height=BODY_HEIGHT))
        self.body.setTwoSided(True)
        mat = Material()                         # black coat with a slight sheen
        mat.setDiffuse(Vec4(0.04, 0.04, 0.045, 1.0))
        mat.setAmbient(Vec4(0.05, 0.05, 0.055, 1.0))
        mat.setSpecular(Vec4(0.35, 0.35, 0.40, 1.0))
        mat.setShininess(40.0)
        self.body.setMaterial(mat, 1)
 
        # nametag + speech pop, both always facing the camera and drawn on top of walls
        self.tag_root = app.render.attachNewNode("anna-tag")
        self.tag = self._make_text(self.tag_root, self.NAME, 0.65, 1.35, (1.0, 0.95, 0.80, 1.0))
        self.pop = self._make_text(self.tag_root, "", 0.5, 2.0, (1.0, 0.85, 0.30, 1.0))
        self._pop_time = 0.0
 
        self.bite_cd = 0.0
        self.bark_cd = 0.0
        self.bark_time = 0.0
        self.mode = "guard"            # guard | bite | bark
        self.kills = 0
 
        self._path: list[tuple[float, float]] = []
        self._path_timer = 0.0
        self._path_goal = None
 
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_text(parent: NodePath, text: str, scale: float, z: float, colour) -> TextNode:
        tn = TextNode("anna-text")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(*colour)
        tn.setShadow(0.05, 0.05)
        tn.setShadowColor(0, 0, 0, 0.9)
        np = parent.attachNewNode(tn)
        np.setScale(scale)
        np.setZ(z)
        np.setBillboardPointEye()
        np.setLightOff()
        np.setDepthTest(False)
        np.setDepthWrite(False)
        np.setBin("fixed", 60)
        return tn
 
    @property
    def position(self) -> Vec3:
        return self.node.getPos()
 
    def _say(self, text: str, seconds: float = 0.9) -> None:
        self.pop.setText(text)
        self._pop_time = seconds
 
    # ------------------------------------------------------------------ #
    #  Movement (straight when the way is clear, A* otherwise; Anna can't break doors)
    # ------------------------------------------------------------------ #
    def _move_toward(self, tx: float, ty: float, stop: float, dt: float, speed: float) -> bool:
        """Returns True once within `stop` of the target."""
        pos = self.position
        if _hyp(pos.x, pos.y, tx, ty) <= stop:
            self._path = []
            return True
 
        col = self.world.collision
        ex, ey = col.sweep(pos.x, pos.y, tx, ty, self.radius, step=0.1)
        if _hyp(ex, ey, tx, ty) < 0.1:
            waypoint = (tx, ty)
            self._path = []
        else:
            self._path_timer -= dt
            goal_cell = self.swarm.nav.cell_of(tx, ty)
            if self._path_timer <= 0.0 or goal_cell != self._path_goal or not self._path:
                self._path_timer = 0.35
                self._path_goal = goal_cell
                found = self.swarm.nav.find_path((pos.x, pos.y), (tx, ty), max(stop, 1.0),
                                                 allow_break=False)
                self._path = [(x, y) for x, y, _ in found] if found else []
            while self._path and _hyp(pos.x, pos.y, *self._path[0]) < 0.3:
                self._path.pop(0)
            if not self._path:
                return False                        # no way through (e.g. closed door)
            waypoint = self._path[0]
            for k in range(min(len(self._path), 6) - 1, 0, -1):
                wx, wy = self._path[k]
                sx, sy = col.sweep(pos.x, pos.y, wx, wy, self.radius, step=0.1)
                if _hyp(sx, sy, wx, wy) < 0.05:
                    waypoint = (wx, wy)
                    del self._path[:k]
                    break
 
        dx, dy = waypoint[0] - pos.x, waypoint[1] - pos.y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return False
        step = min(speed * dt, dist)
        self._place(pos.x + dx / dist * step, pos.y + dy / dist * step)
        self.node.setH(-yaw_from_dir(dx, dy))
        return False
 
    def _place(self, x: float, y: float) -> None:
        x, y = self.world.collision.resolve(x, y, self.radius)
        # leash: pull back onto the circle around the player
        p = self.player.agent_position
        d = _hyp(x, y, p.x, p.y)
        if d > self.LEASH:
            x, y = p.x + (x - p.x) / d * self.LEASH, p.y + (y - p.y) / d * self.LEASH
            x, y = self.world.collision.resolve(x, y, self.radius)
        self.node.setPos(x, y, self.world.height_at(x, y))
 
    # ------------------------------------------------------------------ #
    #  Actions
    # ------------------------------------------------------------------ #
    def _bark(self, minions) -> None:
        pos = self.position
        scared = sorted(minions, key=lambda m: _hyp(m.position.x, m.position.y, pos.x, pos.y))
        n = 0
        for m in scared:
            if n >= self.BARK_MAX:
                break
            if _hyp(m.position.x, m.position.y, pos.x, pos.y) > self.BARK_RADIUS:
                break
            if m.fleeing or m.confident:
                continue
            m.scare(lambda: (self.position.x, self.position.y), self.BARK_FLEE)
            n += 1
        if n == 0:
            return                                     # nobody scareable: don't waste the bark
        self.mode = "bark"
        self.bark_time = self.BARK_CHASE
        self.bark_cd = self.BARK_COOLDOWN
        self._say("Woof woof!", 1.2)
 
    def _bite(self, minion) -> None:
        minion.kill()
        self.kills += 1
        self.bite_cd = self.BITE_COOLDOWN
        self._say("Chomp!", 0.7)
        self.node.setScale(1.25)                       # little pounce
 
    # ------------------------------------------------------------------ #
    def update(self, dt: float) -> None:
        if dt <= 0.0:
            return
 
        self.bite_cd = max(0.0, self.bite_cd - dt)
        self.bark_cd = max(0.0, self.bark_cd - dt)
        self.bark_time = max(0.0, self.bark_time - dt)
        if self._pop_time > 0.0:
            self._pop_time -= dt
            if self._pop_time <= 0.0:
                self.pop.setText("")
        s = self.node.getScale().x
        if s > 1.0:
            self.node.setScale(max(1.0, s - dt * 1.5))
 
        pl = self.player.agent_position
        me = self.position
 
        near_player = [m for m in self.swarm.alive()
                       if _hyp(m.position.x, m.position.y, pl.x, pl.y) <= self.ENGAGE]
        active = [m for m in near_player if not m.fleeing]
        crowd = [m for m in self.swarm.alive()
                 if not m.fleeing and not m.confident
                 and _hyp(m.position.x, m.position.y, me.x, me.y) <= self.CROWD_RADIUS]
 
        if self.bark_time > 0.0:
            # herding: chase the scared minions away, no biting
            self.mode = "bark"
            scared = [m for m in near_player if m.fleeing]
            if scared:
                t = min(scared, key=lambda m: _hyp(m.position.x, m.position.y, me.x, me.y))
                self._move_toward(t.position.x, t.position.y, 1.0, dt, self.speed)
            else:
                self.bark_time = 0.0
        elif len(crowd) >= self.BARK_CROWD and self.bark_cd <= 0.0:
            self._bark(crowd)
        elif active:
            # protect the player: go for the minion closest to them
            self.mode = "bite"
            t = min(active, key=lambda m: _hyp(m.position.x, m.position.y, pl.x, pl.y))
            tx, ty = t.position.x, t.position.y
            if _hyp(me.x, me.y, tx, ty) <= self.BITE_RANGE:
                if self.bite_cd <= 0.0:
                    self._bite(t)
            else:
                self._move_toward(tx, ty, self.BITE_RANGE * 0.8, dt, self.speed)
        else:
            self.mode = "guard"
            far = _hyp(me.x, me.y, pl.x, pl.y) > self.LEASH * 0.8
            self._move_toward(pl.x, pl.y, self.HEEL, dt, self.speed * (1.2 if far else 1.0))
 
        # nametag follows the dog
        p = self.position
        self.tag_root.setPos(p.x, p.y, 0.0)
 
 
def _spawn_xy():
    from src import layout
    return layout.anna_spawn_point()
