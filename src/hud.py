from __future__ import annotations

import os

from panda3d.core import Filename, TextNode, TransparencyAttrib

_BOLD_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)

RED = (0.92, 0.10, 0.08, 1.0)
DARK_RED = (0.25, 0.0, 0.0, 1.0)


def _load_bold_font(loader):
    for path in _BOLD_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                font = loader.loadFont(Filename.fromOsSpecific(path).getFullpath())
            except Exception:
                font = None
            if font is not None and font.isValid():
                return font
    return None          # falls back to Panda's default font + a heavy shadow


class WaveBanner:
    ANNOUNCE_HOLD = 2.5 # seconds fully visible
    ANNOUNCE_FADE = 1.0

    def __init__(self, app) -> None:
        self.title_text = ''
        self.countdown_text = ''
        self._announce_age = None
        self.title = self.countdown = None

        aspect2d = getattr(app, "aspect2d", None)
        if aspect2d is None:                 # headless
            return

        from direct.gui.OnscreenText import OnscreenText
        font = _load_bold_font(app.loader)

        def make(scale, y):
            kw = dict(text="", parent=aspect2d, pos=(0.0, y), scale=scale, fg=RED,
                      shadow=DARK_RED, align=TextNode.ACenter, mayChange=True)
            if font is not None:
                kw["font"] = font
            t = OnscreenText(**kw)
            t.setTransparency(TransparencyAttrib.MAlpha)
            if font is None:                 # fake bold: heavy outline-ish shadow
                t.textNode.setShadow(0.04, 0.04)
            return t

        self.title = make(0.16, 0.80)
        self.countdown = make(0.095, 0.82)

    def announce(self, text: str) -> None:
        self.title_text = text
        self._announce_age = 0.0
        if self.title is not None:
            self.title.setText(text)
            self.title.setColorScale(1, 1, 1, 1)

    def hide_announcement(self) -> None:
        self.title_text = ""
        self._announce_age = None
        if self.title is not None:
            self.title.setText("")

    def set_countdown(self, text: str) -> None:
        self.countdown_text = text
        if self.countdown is not None:
            self.countdown.setText(text)

    def update(self, dt: float) -> None:
        if self._announce_age is None:
            return
        self._announce_age += dt
        fade_t = self._announce_age - self.ANNOUNCE_HOLD
        if fade_t >= self.ANNOUNCE_FADE:
            self.hide_announcement()
        elif fade_t > 0 and self.title is not None:
            self.title.setColorScale(1, 1, 1, 1.0 - fade_t / self.ANNOUNCE_FADE)
