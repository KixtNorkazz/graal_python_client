"""Settings (F1): sound on/off and the volume of sound effects and of looped sounds (the waves of portwolfe, other ambience).

Kept in `settings.json` in the project folder (the Android app points PATH into its private folder). The window is pure logic plus `draw()`;
the viewer feeds it keys and clicks: Up/Down choose a row, Left/Right (or the - / + buttons) change it, Enter or a click toggles, Esc / F1 close."""
import json, os
from PIL import ImageDraw
import render

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "settings.json")   # in the project folder, one above engine/
DEFAULTS = {"sound": True, "effects_volume": 80, "loop_volume": 40}
ROWS = (("sound", "Sound"), ("effects_volume", "Sound effects"), ("loop_volume", "Looped sounds (waves, ambience)"))
STEP = 10
PANEL = (120, 80, 400)   # x, y, width (logical 640x480)
ROW_H = 34


def load(defaults=None):
    """The saved settings over the defaults; a damaged or missing file gives the defaults."""
    out = dict(defaults or DEFAULTS)
    try:
        raw = json.load(open(PATH, encoding="utf-8"))
        for k, v in raw.items():
            if k in out and type(v) is type(out[k]): out[k] = v
    except (OSError, ValueError): pass
    for k in ("effects_volume", "loop_volume"): out[k] = max(0, min(100, int(out[k])))
    return out


def save(values):
    try:
        with open(PATH + ".part", "w", encoding="utf-8") as f: json.dump(values, f)
        os.replace(PATH + ".part", PATH)
    except OSError: pass


def apply(s, values):
    """Give the session's audio the volumes (0..1) and the on/off switch."""
    a = getattr(s, "audio", None)
    if a is None: return
    a.set_volumes(values["effects_volume"] / 100 if values["sound"] else 0.0, values["loop_volume"] / 100 if values["sound"] else 0.0)


class SettingsWindow:
    def __init__(self, values=None):
        self.open = False; self.cursor = 0; self.values = values if values is not None else load(); self.panel = PANEL   # (x, y, width): the phone centres it

    def toggle(self, s=None): self.open = not self.open

    def _change(self, s, row, delta):
        key = ROWS[row][0]
        if key == "sound": self.values["sound"] = not self.values["sound"] if delta else self.values["sound"]
        else: self.values[key] = max(0, min(100, self.values[key] + delta * STEP))
        apply(s, self.values); save(self.values)

    def key(self, sym, s):
        """A key while the window is open (SDL keysyms). Returns True if used."""
        import window
        if sym == window.K_UP: self.cursor = (self.cursor - 1) % len(ROWS)
        elif sym == window.K_DOWN: self.cursor = (self.cursor + 1) % len(ROWS)
        elif sym == window.K_LEFT: self._change(s, self.cursor, -1)
        elif sym == window.K_RIGHT: self._change(s, self.cursor, 1)
        elif sym in (window.K_RETURN, ord(" ")) and ROWS[self.cursor][0] == "sound": self._change(s, self.cursor, 1)
        elif sym in (window.K_ESCAPE, K_F1): self.open = False
        return True

    def _buttons(self, row):
        px, py, pw = self.panel; y = py + 40 + row * ROW_H
        return (px + pw - 120, y, px + pw - 90, y + 24), (px + pw - 40, y, px + pw - 10, y + 24)

    def _close_box(self):
        px, py, pw = self.panel; h = 40 + len(ROWS) * ROW_H + 40
        return (px + pw // 2 - 40, py + h - 32, px + pw // 2 + 40, py + h - 8)

    def click(self, x, y, s):
        """Press at logical (x, y). Returns True if the window used it."""
        if not self.open: return False
        px, py, pw = self.panel; h = 40 + len(ROWS) * ROW_H + 40
        cx0, cy0, cx1, cy1 = self._close_box()
        if cx0 <= x < cx1 and cy0 <= y < cy1: self.open = False; return True
        for row in range(len(ROWS)):
            minus, plus = self._buttons(row)
            for box, delta in ((minus, -1), (plus, 1)):
                if box[0] <= x < box[2] and box[1] <= y < box[3]: self.cursor = row; self._change(s, row, delta); return True
            if px <= x < px + pw and py + 40 + row * ROW_H <= y < py + 40 + (row + 1) * ROW_H:
                self.cursor = row
                if ROWS[row][0] == "sound": self._change(s, row, 1)
                return True
        return px <= x < px + pw and py <= y < py + h

    def _value_text(self, key):
        v = self.values[key]
        if key == "sound": return "On" if v else "Off"
        return f"{v} %" if self.values["sound"] else f"({v} %)"

    def draw(self, out, s=None, hint="Up/Down choose   Left/Right change   F1 or Esc close"):
        if not self.open: return
        px, py, pw = self.panel; h = 40 + len(ROWS) * ROW_H + 40
        d = ImageDraw.Draw(out, "RGBA")
        d.rectangle((px, py, px + pw, py + h), fill=(20, 24, 40, 230), outline=(240, 220, 130, 255), width=2)
        render.draw_chat(out, "Settings", px + pw // 2, py + 22)
        for row, (key, label) in enumerate(ROWS):
            y = py + 40 + row * ROW_H
            if row == self.cursor: d.rectangle((px + 4, y - 2, px + pw - 4, y + ROW_H - 6), fill=(70, 90, 150, 200))
            render.draw_chat(out, label, px + 14 + len(label) * 3, y + 18)
            minus, plus = self._buttons(row)
            for box, sign in ((minus, "-"), (plus, "+")):
                d.rectangle(box, fill=(60, 70, 110, 255), outline=(240, 220, 130, 255))
                render.draw_chat(out, sign, (box[0] + box[2]) // 2, box[3] - 6)
            render.draw_chat(out, self._value_text(key), (minus[2] + plus[0]) // 2, y + 18)
        cb = self._close_box(); d.rectangle(cb, fill=(60, 70, 110, 255), outline=(240, 220, 130, 255))
        render.draw_chat(out, "Close", (cb[0] + cb[2]) // 2, cb[3] - 6)
        if hint: render.draw_chat(out, hint, px + pw // 2, py + h + 16)


K_F1 = 0x4000003A
