import math
from panda3d.core import InputDevice


DEADZONE = 0.2

class Gamepad:
    # Triangle is the top face button (face_y in Panda3D's layout)
    INTERACT_EVENTS = (
        "gamepad-face_y",
        "gamepad-face-y",
        "gamepad-face-top",
        "gamepad-north",
        "gamepad-button-3",
    )

    def __init__(self, app, on_dash, on_interact=None, on_interact_release=None) -> None:
        self.app = app
        self._on_dash = on_dash
        self._on_interact = on_interact
        self._on_interact_release = on_interact_release
        self._pad = None

        app.accept("connect-device", self._connected)
        app.accept("disconnect-device", self._disconnected)

        for pad in app.devices.getDevices(InputDevice.DeviceClass.gamepad):
            self._connected(pad)
        for pad in app.devices.getDevices(InputDevice.DeviceClass.unknown):
            self._connected(pad)

    def _connected(self, device) -> None:
        if self._pad is not None:
            return
        if device.device_class in (InputDevice.DeviceClass.keyboard, InputDevice.DeviceClass.mouse):
            return

        self._pad = device
        self.app.attachInputDevice(device, prefix="gamepad")

        for event_name in ("gamepad-face-a","gamepad-face_a","gamepad-face-bottom","gamepad-south","gamepad-button-0"):
            self.app.accept(event_name, self._on_dash)

        if self._on_interact is not None:
            for event_name in self.INTERACT_EVENTS:
                self.app.accept(event_name, self._on_interact)
                if self._on_interact_release is not None:
                    self.app.accept(event_name + "-up", self._on_interact_release)

    def _disconnected(self, device) -> None:
        if device is not self._pad:
            return
        for event_name in ("gamepad-face-a", "gamepad-face_a", "gamepad-face-bottom", "gamepad-south", "gamepad-button-0"):
            self.app.ignore(event_name)
        for event_name in self.INTERACT_EVENTS:
            self.app.ignore(event_name)
            self.app.ignore(event_name + "-up")
        self.app.detachInputDevice(device)
        self._pad = None

    def stick(self) -> tuple[float, float]:
        if not self._pad:
            return 0.0, 0.0

        x = 0.0
        y = 0.0
        axes = {a.axis: a.value for a in self._pad.axes}

        if InputDevice.Axis.left_x in axes and InputDevice.Axis.left_y in axes:
            x = axes[InputDevice.Axis.left_x]
            y = axes[InputDevice.Axis.left_y]
        elif InputDevice.Axis.x in axes and InputDevice.Axis.y in axes:
            x = axes[InputDevice.Axis.x]
            y = axes[InputDevice.Axis.y]
        elif InputDevice.Axis.z in axes and InputDevice.Axis.rz in axes:
            x = axes[InputDevice.Axis.z]
            y = axes[InputDevice.Axis.rz]
        elif len(self._pad.axes) >= 2:
            x = self._pad.axes[0].value
            y = self._pad.axes[1].value

        y = y

        mag = math.hypot(x, y)
        if mag < DEADZONE:
            return 0.0, 0.0

        norm = min(1.0, (mag - DEADZONE) / (1.0 - DEADZONE))
        return (x / mag) * norm, (y / mag) * norm
