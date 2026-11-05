import math
from panda3d.core import InputDevice


DEADZONE = 0.2
DEBUG = False        # True: print which device/buttons are bound (and log every input event)

SONY = 0x054C
# Sony pads Panda3D already knows how to map on Windows (DualShock 4, DS4 v2, DS4 wireless adapter).
PANDA_KNOWN_SONY = {0x05C4, 0x09CC, 0x0BA0}

# Button names Panda3D reports (event = "gamepad-<name>"), per physical button.
# Panda's DS4 preset and XInput (what DS4Windows emulates) both give: Cross=face_a, Square=face_x,
# Triangle=face_y, R1=rshoulder.
LAYOUT_STANDARD = {"dash": "face_a", "shoot": "face_x", "interact": "face_y", "reload": "rshoulder"}
# Sony pad Panda has no preset for (e.g. DualSense): raw HID order is Square, Cross, Circle, Triangle,
# which Panda's generic mapping labels face_a, face_b, face_x, face_y.
LAYOUT_SONY_RAW = {"dash": "face_b", "shoot": "face_a", "interact": "face_y", "reload": "rshoulder"}


class Gamepad:
    def __init__(self, app, on_dash, on_interact=None, on_interact_release=None) -> None:
        self.app = app
        self._on_dash = on_dash
        self._on_interact = on_interact
        self._on_interact_release = on_interact_release
        self.on_shoot = None
        self.on_reload = None

        self._pad = None
        self._pad_score = -1
        self._bound: list[str] = []

        app.accept("connect-device", self._connected)
        app.accept("disconnect-device", self._disconnected)
        self._scan()

        if DEBUG:
            app.messenger.toggleVerbose()

    # ------------------------------------------------------------ device handling
    def _scan(self, exclude=None) -> None:
        devices = []
        for cls in (InputDevice.DeviceClass.gamepad, InputDevice.DeviceClass.unknown):
            devices.extend(self.app.devices.getDevices(cls))
        for pad in devices:
            if pad is not exclude:
                self._connected(pad)

    @staticmethod
    def _ids(device) -> tuple[int, int]:
        return int(getattr(device, "vendor_id", 0) or 0), int(getattr(device, "product_id", 0) or 0)

    # Native PS4 pads show up as plain gamepads; other HID junk (keyboard extras, headsets) can show
    # up as "unknown", so those only count if they actually have sticks.
    def _score(self, device) -> int:
        cls = device.device_class
        if cls == InputDevice.DeviceClass.gamepad:
            score = 10
        elif cls == InputDevice.DeviceClass.unknown and len(device.axes) >= 2:
            score = 1
        else:
            return -1
        if self._ids(device)[0] == SONY:
            score += 5
        return score

    def _layout_for(self, device) -> dict:
        vendor, product = self._ids(device)
        if vendor == SONY and product not in PANDA_KNOWN_SONY:
            return LAYOUT_SONY_RAW
        return LAYOUT_STANDARD

    def _connected(self, device) -> None:
        score = self._score(device)
        if score < 0 or score <= self._pad_score:
            return
        if self._pad is not None:
            self._unbind()

        self._pad, self._pad_score = device, score
        self.app.attachInputDevice(device, prefix="gamepad")
        layout = self._layout_for(device)

        def bind(button, handler, up_handler=None):
            event = f"gamepad-{button}"
            self.app.accept(event, handler)
            self._bound.append(event)
            if up_handler is not None:
                self.app.accept(event + "-up", up_handler)
                self._bound.append(event + "-up")

        bind(layout["dash"], self._on_dash)
        if self._on_interact is not None:
            bind(layout["interact"], self._on_interact, self._on_interact_release)
        bind(layout["shoot"], self._fire_shoot)
        bind(layout["reload"], self._fire_reload)

        vendor, product = self._ids(device)
        print(f"[Gamepad] using '{device.name}' (VID {vendor:04x} PID {product:04x}); "
              f"dash={layout['dash']} shoot={layout['shoot']} "
              f"interact={layout['interact']} reload={layout['reload']}")

    def _unbind(self) -> None:
        for event in self._bound:
            self.app.ignore(event)
        self._bound = []
        if self._pad is not None:
            self.app.detachInputDevice(self._pad)
        self._pad, self._pad_score = None, -1

    def _disconnected(self, device) -> None:
        if device is not self._pad:
            return
        self._unbind()
        self._scan(exclude=device)

    def _fire_shoot(self) -> None:
        if self.on_shoot is not None:
            self.on_shoot()

    def _fire_reload(self) -> None:
        if self.on_reload is not None:
            self.on_reload()

    # ------------------------------------------------------------ sticks
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

        mag = math.hypot(x, y)
        if mag < DEADZONE:
            return 0.0, 0.0

        norm = min(1.0, (mag - DEADZONE) / (1.0 - DEADZONE))
        return (x / mag) * norm, (y / mag) * norm
