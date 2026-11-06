from __future__ import annotations

import sys


# Windows only: always draws the game window's title bar in dark mode, whatever the system theme is.
def apply_dark_mode(base) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.c_void_p(base.win.getWindowHandle().getIntHandle())
        value = ctypes.c_int(1)
        dwm = ctypes.windll.dwmapi
        # attribute 20 on Windows 10 20H1+/11, 19 on older Windows 10 builds
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        # force the frame to redraw so the change shows immediately
        # (NOMOVE | NOSIZE | NOZORDER | NOACTIVATE | FRAMECHANGED)
        ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception as exc:
        print(f"[window] could not apply dark title bar: {exc}")
