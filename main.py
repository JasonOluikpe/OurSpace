from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData, ClockObject, Vec3

from src.camera import FollowCamera
from src.world import World
from src.player import Player
from src.swarm import Swarm
from src.anna import Anna
from src.gun import Gun
from src.cutscene import Cutscene
from src.boss import Boss
from src.win_theme import apply_dark_mode


loadPrcFileData(
    '',
    '\n'.join((
        'window-title OurSpace',
        'win-size 1600 900',
        'framebuffer-multisample 1',
        'multisamples 4',
        'depth-bits 24',
        'sync-video 0',
        'cursor-hidden true',
    )),
)


class Game(ShowBase):
    def __init__(self) -> None:
        super().__init__()
        apply_dark_mode(self)

        self.world = World(self)
        self.player = Player(self, self.world)
        self.camera_rig = FollowCamera(self, self.player.node, self.world)

        self.swarm = Swarm(self, self.world, self.player)
        self.anna = Anna(self, self.world, self.player, self.swarm)

        self.gun = Gun(self, self.world, self.player, self.swarm)
        self.cutscene = Cutscene(self, self.world, self.player)   # monitor alert + WeChat cut scene
        self.boss = Boss(self, self.world, self.camera_rig, self.player, self.anna, self.swarm)
        self.cutscene.on_finished.append(self.boss.start)         # boss entrance plays right after the cut scene

        # debug
        self.accept('escape', self.userExit)
        self.accept('k', self.swarm.kill_all)
        self.accept('b', self.boss.start, [True])
        self.accept('1', self.boss.debug_attack, [1])
        self.accept('2', self.boss.debug_attack, [2])
        self.accept('m', self.swarm.spawn_group)
        
        self.taskMgr.add(self._update, 'update')

    def _update(self, task):
        raw_dt = ClockObject.getGlobalClock().getDt()
        if self.cutscene.active:                    # game is frozen while the cut scene plays
            self.cutscene.update(min(raw_dt, 0.1))
            return task.cont
        dt = min(raw_dt, 1.0 / 60.0)
        self.player.update(dt, self.camera_rig.yaw)
        self.gun.update(dt)
        self.swarm.update(dt)
        self.anna.update(dt)
        self.boss.update(dt)
        self.camera_rig.update(dt)
        self.cutscene.update(dt)
        self.world.update(dt, self.camera.getPos(self.render), self.player.agent_position + Vec3(0.0, 0.0, 1.0))
        return task.cont


if __name__ == '__main__':
    Game().run()
