from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData, ClockObject, Vec3

from src.camera import FollowCamera
from src.world import World
from src.player import Player
from src.swarm import Swarm
from src.waves import WaveManager
from src.anna import Anna
from src.gun import Gun
from src.win_theme import apply_dark_mode


loadPrcFileData(
    '',
    '\n'.join((
        'window-title OurSpace',
        'win-size 1600 900',
        'framebuffer-multisample 1',
        'multisamples 4',
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
        self.waves = WaveManager(self, self.world, self.player, self.swarm)
        self.anna = Anna(self, self.world, self.player, self.swarm)

        self.gun = Gun(self, self.world, self.player, self.swarm)

        self.accept('escape', self.userExit) # debug
        self.accept('k', self.swarm.kill_all) # debug
        self.taskMgr.add(self._update, 'update')

    def _update(self, task):
        dt = min(ClockObject.getGlobalClock().getDt(), 1.0 / 60.0)
        self.player.update(dt, self.camera_rig.yaw)
        self.gun.update(dt)
        self.waves.update(dt)
        self.swarm.update(dt)
        self.anna.update(dt)
        self.camera_rig.update(dt)
        self.world.update(dt, self.camera.getPos(self.render), self.player.agent_position + Vec3(0.0, 0.0, 1.0))
        return task.cont


if __name__ == '__main__':
    Game().run()


# Game Idea: Girl, her boyfriend (co-op multiplayer), and her Dog, defend her apartment from Mind Controlled Minions
# Game Idea: 5 Waves of Minions, each getting progressively harder; boss fight after wave 5

# TODO: Tune Player Dash
# TODO: Implement Player Healthbar
# TODO: Implement Player Dying
# TODO: Implement Multiplayer
