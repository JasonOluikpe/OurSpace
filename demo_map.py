from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData

from src.world import World

loadPrcFileData('', '\n'.join((
    "window-title Demo",
    "win-size 1280 720",
    "framebuffer-multisample 1",
    "multisamples 4",
)))


class MapPreview(ShowBase):
    MIN_ZOOM, MAX_ZOOM, ZOOM_STEP = 6.0, 260.0, 1.12
    ORBIT_SENSITIVITY = 180.0

    def __init__(self) -> None:
        super().__init__()
        self.disableMouse()
        self.world = World(self)

        self.zoom, self.yaw, self.pitch = 62.0, 0.0, -55.0
        self._orbiting = False
        self._last_mouse = None

        self.camLens.setNearFar(0.1, 1000.0)
        self.camLens.setFov(55.0)
        self.pivot = self.render.attachNewNode("pivot")
        self.pivot.setPos(self.world.center)
        self.camera.reparentTo(self.pivot)

        for key in ("wheel_up", "=", "+", "page_up"):
            self.accept(key, self._set_zoom, [1.0 / self.ZOOM_STEP])

        for key in ("wheel_down", "-", "_", "page_down"):
            self.accept(key, self._set_zoom, [self.ZOOM_STEP])

        self.accept("w", self.world.walls_root.toggleVis)
        self.accept("mouse3", self._begin_orbit)
        self.accept("mouse3-up", self._end_orbit)
        self.accept("escape", self.userExit)
        self.taskMgr.add(self._orbit_task, "orbit")
        self._update_camera()

    def _update_camera(self) -> None:
        self.pivot.setHpr(self.yaw, self.pitch, 0.0)
        self.camera.setPos(0.0, -self.zoom, 0.0)

    def _set_zoom(self, factor: float) -> None:
        self.zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self.zoom * factor))
        self._update_camera()

    def _begin_orbit(self) -> None:
        self._orbiting, self._last_mouse = True, None

    def _end_orbit(self) -> None:
        self._orbiting, self._last_mouse = False, None

    def _orbit_task(self, task):
        if not self._orbiting or not self.mouseWatcherNode.hasMouse():
            return task.cont
        m = self.mouseWatcherNode.getMouse()
        cur = (m.getX(), m.getY())
        if self._last_mouse is not None:
            self.yaw -= (cur[0] - self._last_mouse[0]) * self.ORBIT_SENSITIVITY
            self.pitch = max(-89.0, min(-5.0, self.pitch + (cur[1] - self._last_mouse[1]) * self.ORBIT_SENSITIVITY))
            self._update_camera()
        self._last_mouse = cur
        return task.cont


if __name__ == "__main__":
    MapPreview().run()
