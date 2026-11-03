import math

from panda3d.core import InputDevice


Axis = InputDevice.Axis

DEADZONE = 0.2
DASH_BUTTON = "gamepad-face_a"        # Cross
INVERT_Y = False                      # flip if "up" on the stick moves backwards
STICK_AXES = (                        # (x axis, y axis, y is "down = positive")
    (InputDevice.Axis.left_x, InputDevice.Axis.left_y, False),
    (InputDevice.Axis.x, InputDevice.Axis.y, True),     # generic HID stick
)


class Gamepad:
    def __init__(self, app, on_dash) -> None:
        self.app = app
        self._on_dash = on_dash
        self._pad = None
        self._x = self._y = None          # stick axis ids (Axis.*)
        self._flip_y = False

        app.accept("f2", self.print_debug)    # F2: dump raw axis values
        app.accept("connect-device", self._connected)
        app.accept("disconnect-device", self._disconnected)
        for pad in app.devices.getDevices(InputDevice.DeviceClass.gamepad):
            self._connected(pad)

    @property
    def connected(self) -> bool:
        return self._pad is not None

    # ------------------------------------------------------------------ hot-plug
    def _connected(self, device) -> None:
        if self._pad is not None or device.device_class != InputDevice.DeviceClass.gamepad:
            return
        self._pad = device
        self._pick_stick_axes(device)
        self.app.attachInputDevice(device, prefix="gamepad")
        self.app.accept(DASH_BUTTON, self._on_dash)

    def _pick_stick_axes(self, device) -> None:
        present = [a.axis for a in device.axes]
        print(f"[gamepad] {device.name!r}: axes {[str(a) for a in present]}")
        for x_axis, y_axis, flip_y in STICK_AXES:
            if x_axis in present and y_axis in present:
                self._x, self._y = x_axis, y_axis
                self._flip_y = flip_y
                print(f"[gamepad] left stick = {x_axis}/{y_axis}")
                return
        print("[gamepad] no stick axes found; only buttons will work")
        self._x = self._y = None

    def _disconnected(self, device) -> None:
        if device is not self._pad:
            return
        self.app.ignore(DASH_BUTTON)
        self.app.detachInputDevice(device)
        self._pad = self._x = self._y = None

    # ------------------------------------------------------------------ polling
    def stick(self) -> tuple[float, float]:
        if self._x is None:
            return 0.0, 0.0
        # Look the axes up every frame so we always read the live value.
        x = self._pad.findAxis(self._x).value
        y = self._pad.findAxis(self._y).value
        if self._flip_y != INVERT_Y:
            y = -y
        magnitude = math.hypot(x, y)
        if magnitude < DEADZONE:
            return 0.0, 0.0
        scale = (min(magnitude, 1.0) - DEADZONE) / (1.0 - DEADZONE) / magnitude
        return x * scale, y * scale

    def print_debug(self) -> None:
        if self._pad is None:
            print("[gamepad] none connected")
            return
        values = {str(a.axis): round(a.value, 2) for a in self._pad.axes}
        print(f"[gamepad] raw axes: {values}")