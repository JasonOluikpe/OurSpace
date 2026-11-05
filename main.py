from direct.showbase.ShowBase import ShowBase
from panda3d.core import ClockObject, Vec3, loadPrcFileData

from src.camera import FollowCamera
from src.anna import Anna
from src.swarm import Swarm
from src.waves import WaveManager
from src.player import Player
from src.world import World


loadPrcFileData(
    '',
    '\n'.join((
        "window-title OurSpace",
        "win-size 1280 720",
        "framebuffer-multisample 1",
        "multisamples 4",
        "sync-video 0",
    )),
)


class Game(ShowBase):
    def __init__(self) -> None:
        super().__init__()

        self.world = World(self)
        self.player = Player(self, self.world)
        self.swarm = Swarm(self, self.world, self.player)
        self.waves = WaveManager(self, self.world, self.player, self.swarm)
        self.anna = Anna(self, self.world, self.player, self.swarm)
        self.camera_rig = FollowCamera(self, self.player.node, self.world)

        self.accept('escape', self.userExit)
        self.accept('k', self.swarm.kill_all)
        self.taskMgr.add(self._update, 'update')

    def _update(self, task):
        dt = min(ClockObject.getGlobalClock().getDt(), 1.0 / 60.0)
        self.player.update(dt, self.camera_rig.yaw)
        self.waves.update(dt)
        self.swarm.update(dt)
        self.anna.update(dt)
        self.camera_rig.update(dt)
        self.world.update(dt, self.camera.getPos(self.render), self.player.agent_position + Vec3(0.0, 0.0, 1.0))
        return task.cont


if __name__ == '__main__':
    Game().run()
