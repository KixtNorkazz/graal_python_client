"""Small modal dialogs for the level editor: a form with text fields (some with several lines) and a list to choose a file from.

`handle(event, mod)` takes the events of window.Window and returns None while the dialog is open, then ("ok", values), ("cancel", None) or (button, values)
for an extra button. `draw(canvas)` paints it centred on a PIL image."""
from PIL import ImageDraw
import window

LINE_H = 12
K_HOME, K_END, K_DELETE = 0x4000004A, 0x4000004D, 127
BG, EDGE, TEXT, DIM, HOT, ERR = (20, 24, 40, 240), (240, 220, 130, 255), (255, 255, 255, 255), (170, 175, 190, 255), (255, 240, 160, 255), (255, 150, 130, 255)


class Field:
    def __init__(self, key, label, value="", lines=1, width=34):
        self.key, self.label, self.lines, self.width = key, label, lines, width
        self.value = str(value)

    @property
    def value(self): return self._value

    @value.setter
    def value(self, text): self._value = text; self.pos = len(text)

    def insert(self, text): pos = self.pos + len(text); self._value = self._value[:self.pos] + text + self._value[self.pos:]; self.pos = pos

    def backspace(self):
        if self.pos: self._value = self._value[:self.pos - 1] + self._value[self.pos:]; self.pos -= 1

    def delete(self): self._value = self._value[:self.pos] + self._value[self.pos + 1:]

    def _line_start(self): return self.value.rfind("\n", 0, self.pos) + 1

    def move(self, key):
        """Left / Right / Home / End, and Up / Down between the lines of a field with several lines. Returns False if the key moves nothing."""
        start = self._line_start(); col = self.pos - start
        if key == window.K_LEFT: self.pos = max(0, self.pos - 1)
        elif key == window.K_RIGHT: self.pos = min(len(self.value), self.pos + 1)
        elif key == K_HOME: self.pos = start
        elif key == K_END: e = self.value.find("\n", self.pos); self.pos = len(self.value) if e < 0 else e
        elif key == window.K_UP and start > 0:
            ps = self.value.rfind("\n", 0, start - 1) + 1; self.pos = min(ps + col, start - 1)
        elif key == window.K_DOWN:
            e = self.value.find("\n", self.pos)
            if e < 0: return False
            ne = self.value.find("\n", e + 1); ne = len(self.value) if ne < 0 else ne; self.pos = min(e + 1 + col, ne)
        else: return False
        return True


class Form:
    def __init__(self, title, fields, buttons=(), hint="", check=None, width=460):
        """fields: [Field]; buttons: extra button names (e.g. "delete"); check(values) -> error text or ""."""
        self.title, self.fields, self.buttons, self.hint, self.check = title, fields, list(buttons), hint, check
        self.focus, self.error, self.width = 0, "", width

    def values(self): return {f.key: f.value for f in self.fields}

    def _finish(self, name):
        v = self.values()
        if name == "ok" and self.check:
            self.error = self.check(v) or ""
            if self.error: return None
        return (name, v)

    def handle(self, ev, mod=0):
        f = self.fields[self.focus]
        if ev[0] == "text": f.insert(ev[1])
        elif ev[0] == "down":
            k = ev[1]
            if k == window.K_ESCAPE: return ("cancel", None)
            if k == window.K_TAB: self.focus = (self.focus + (-1 if mod & window.KMOD_SHIFT else 1)) % len(self.fields)
            elif k == window.K_BACKSPACE: f.backspace()
            elif k == K_DELETE: f.delete()
            elif k in (window.K_LEFT, window.K_RIGHT, K_HOME, K_END): f.move(k)
            elif k == window.K_RETURN:
                if f.lines > 1 and not mod & window.KMOD_CTRL: f.insert("\n")
                else: return self._finish("ok")
            elif k in (window.K_UP, window.K_DOWN):
                if f.lines > 1 and f.move(k): pass
                elif len(self.fields) > 1: self.focus = (self.focus + (1 if k == window.K_DOWN else -1)) % len(self.fields)
            elif 0x4000003A <= k <= 0x40000045 and 0x4000003A + len(self.buttons) > k: return self._finish(self.buttons[k - 0x4000003A])
        elif ev[0] == "mousedown" and ev[1] == 1:
            for i, r in enumerate(self._rects):
                if r[0] <= ev[2] < r[0] + r[2] and r[1] <= ev[3] < r[1] + r[3]: self.focus = i
        return None

    _rects = ()

    def draw(self, canvas):
        d = ImageDraw.Draw(canvas, "RGBA"); w = self.width
        rows = sum(max(1, f.lines) for f in self.fields); h = 44 + rows * LINE_H + len(self.fields) * 8 + 34 + (14 if self.error else 0) + (14 if self.hint else 0)
        x0, y0 = (canvas.size[0] - w) // 2, max(10, (canvas.size[1] - h) // 3)
        d.rectangle((x0, y0, x0 + w, y0 + h), fill=BG, outline=EDGE, width=2)
        d.text((x0 + 10, y0 + 8), self.title, fill=HOT); y = y0 + 28; rects = []
        for i, f in enumerate(self.fields):
            hot = i == self.focus; ht = max(1, f.lines) * LINE_H + 4
            d.text((x0 + 10, y + 2), f.label, fill=TEXT if hot else DIM)
            d.rectangle((x0 + 130, y, x0 + w - 10, y + ht), fill=(250, 250, 244, 255) if hot else (60, 66, 88, 255), outline=EDGE if hot else DIM)
            text = f.value[:f.pos] + ("|" if hot else "") + f.value[f.pos:]; lines = text.split("\n"); row = text[:f.pos].count("\n")
            first = max(0, min(row - f.lines + 1, len(lines) - f.lines))
            for j, ln in enumerate(lines[first:first + f.lines]):
                col = f.pos - (f.value.rfind("\n", 0, f.pos) + 1) if first + j == row else len(ln)
                cut = max(0, min(col + 1, len(ln)) - f.width); d.text((x0 + 134, y + 2 + j * LINE_H), ln[cut:cut + f.width], fill=(20, 20, 20, 255) if hot else TEXT)
            rects.append((x0 + 130, y, w - 140, ht)); y += ht + 8
        self._rects = rects
        if self.error: d.text((x0 + 10, y), self.error, fill=ERR); y += 14
        keys = "Enter = OK" if all(f.lines == 1 for f in self.fields) else "Ctrl+Enter = OK, Enter = new line"
        extra = "".join("   F%d = %s" % (i + 1, b) for i, b in enumerate(self.buttons))
        d.text((x0 + 10, y + 4), f"{keys}   Tab = next   Esc = cancel{extra}", fill=DIM)
        if self.hint: d.text((x0 + 10, y + 16), self.hint, fill=DIM)


class Chooser:
    """A list to pick from; typing filters it (Up/Down, Enter, Esc)."""
    def __init__(self, title, items):
        self.title, self.items, self.text, self.cursor = title, sorted(items, key=str.lower), "", 0

    def shown(self):
        t = self.text.lower(); return [i for i in self.items if t in i.lower()]

    def handle(self, ev, mod=0):
        rows = self.shown()
        if ev[0] == "text": self.text += ev[1]; self.cursor = 0
        elif ev[0] == "down":
            k = ev[1]
            if k == window.K_ESCAPE: return ("cancel", None)
            if k == window.K_BACKSPACE: self.text = self.text[:-1]; self.cursor = 0
            elif k == window.K_DOWN and rows: self.cursor = (self.cursor + 1) % len(rows)
            elif k == window.K_UP and rows: self.cursor = (self.cursor - 1) % len(rows)
            elif k == window.K_RETURN: return ("ok", rows[self.cursor]) if rows else ("ok", self.text) if self.text else None
        elif ev[0] == "mousedown" and ev[1] == 1:
            x0, y0, w = self._box; i = int((ev[3] - y0 - 40) // LINE_H)
            if x0 <= ev[2] < x0 + w and 0 <= i < min(len(rows), 18):
                if i + self._first == self.cursor: return ("ok", rows[self.cursor])
                self.cursor = i + self._first
        return None

    _box, _first = (0, 0, 0), 0

    def draw(self, canvas):
        d = ImageDraw.Draw(canvas, "RGBA"); rows = self.shown(); w = 380
        self._first = max(0, min(self.cursor - 9, len(rows) - 18)); view = rows[self._first:self._first + 18]
        h = 56 + max(1, len(view)) * LINE_H + 8; x0, y0 = (canvas.size[0] - w) // 2, max(10, (canvas.size[1] - h) // 3); self._box = (x0, y0, w)
        d.rectangle((x0, y0, x0 + w, y0 + h), fill=BG, outline=EDGE, width=2)
        d.text((x0 + 10, y0 + 8), self.title, fill=HOT); d.text((x0 + 10, y0 + 22), "Filter: " + self.text + "_", fill=TEXT)
        if not view: d.text((x0 + 10, y0 + 44), "(nothing found; Enter uses the typed name)" if self.text else "(nothing here)", fill=DIM)
        for i, name in enumerate(view):
            sel = self._first + i == self.cursor; y = y0 + 40 + i * LINE_H
            if sel: d.rectangle((x0 + 6, y, x0 + w - 6, y + LINE_H - 1), fill=(250, 250, 244, 255))
            d.text((x0 + 10, y), name[:56], fill=(20, 20, 20, 255) if sel else TEXT)
