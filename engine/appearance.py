"""The appearance window (F): choose a head and a body from what the server has, see yourself with them, and press Done to wear them.

The lists are the text files `heads.txt` and `bodies.txt` in the server's world folder (made by `server/make_appearance_lists.py`; every client fetches them like any
other file). Without them the folders `heads/` and `bodies/` of the local asset folders are listed, and a file name can be typed in. Done sends the head and body
properties silently, the same as `sethead` and `setbody` do, so the server keeps them with the account."""
import os, time
from PIL import Image, ImageDraw
import assets, config, render, window

COLS, ROWS, CELL = 7, 5, 54
KINDS = (("heads", "Heads"), ("bodies", "Bodies"))
IMAGE_EXT = (".png", ".gif", ".mng", ".jpg")
BG, EDGE, TEXT, DIM, HOT = (20, 24, 40, 245), (240, 220, 130, 255), (255, 255, 255, 255), (170, 175, 190, 255), (255, 240, 160, 255)


def read_names(path):
    try:
        with open(path, encoding="latin1") as f: names = [ln.strip() for ln in f.read().replace("\r", "").split("\n")]
    except OSError: return None
    return [n for n in names if n and os.path.splitext(n)[1].lower() in IMAGE_EXT]


def local_names(kind):
    """Files of the folder `heads` / `bodies` in the local asset folders (empty list when there are none)."""
    seen, out = set(), []
    for root in config.dirs("asset_dirs"):
        for sub in (kind, os.path.join("global", kind)):
            folder = os.path.join(root, sub)
            if os.path.isdir(folder):
                for n in os.listdir(folder):
                    if n.lower() not in seen and os.path.splitext(n)[1].lower() in IMAGE_EXT: seen.add(n.lower()); out.append(n)
    return out


class Appearance:
    def __init__(self):
        self.open = False
        self.tab = "heads"
        self.filter = ""
        self.chosen = {"heads": "", "bodies": ""}
        self.names = {}
        self.cursor = 0
        self.first = 0
        self._shown = {}
        self._asked = 0.0
        self.status = ""
        self.opened_at = 0.0

    def toggle(self, s):
        self.open = not self.open; self.opened_at = time.time()
        if self.open:
            self.chosen = {"heads": str(s.me.get("HEADIMAGE") or ""), "bodies": str(s.me.get("BODYIMAGE") or "")}
            self.filter, self.status = "", ""
            self._focus(s)

    def set_names(self, kind, names): self.names[kind] = list(names)

    def _list(self, kind):
        """The names of one kind, or None while the server's list has not arrived yet."""
        if kind in self.names: return self.names[kind]
        got = read_names(assets.find(kind + ".txt") or "")
        if got is None and assets.fetcher is None: got = local_names(kind)
        if got is not None: self.names[kind] = got
        return got

    def shown(self):
        names = self._list(self.tab)
        if names is None: return None
        key = (self.tab, self.filter, len(names))
        if key not in self._shown:
            f = self.filter.lower(); self._shown = {key: [n for n in names if f in n.lower()]}
        return self._shown[key]

    def _focus(self, s):
        rows = self.shown()
        if rows is None: self.cursor = self.first = 0; return
        cur = self.chosen[self.tab].lower(); idx = next((i for i, n in enumerate(rows) if n.lower() == cur), 0)
        self.cursor = idx; self.first = max(0, idx // COLS * COLS - COLS)

    def _move(self, d):
        rows = self.shown() or []
        if not rows: return
        self.cursor = max(0, min(len(rows) - 1, self.cursor + d)); self.chosen[self.tab] = rows[self.cursor]
        row = self.cursor // COLS * COLS
        if row < self.first: self.first = row
        elif row >= self.first + COLS * ROWS: self.first = row - COLS * (ROWS - 1)

    def done(self, s):
        head, body = self.chosen["heads"], self.chosen["bodies"]
        s.set_appearance(head if head and head != s.me.get("HEADIMAGE") else None, body if body and body != s.me.get("BODYIMAGE") else None)
        self.open = False

    def key(self, sym, s):
        """A key while the window is open. Returns True if used."""
        if sym == window.K_ESCAPE: self.open = False
        elif sym == window.K_TAB: self.tab = "bodies" if self.tab == "heads" else "heads"; self.filter = ""; self._focus(s)
        elif sym == window.K_RETURN:
            rows = self.shown()
            if rows is not None and self.filter and not rows: self.chosen[self.tab] = self.filter; self.status = "using " + self.filter
            else: self.done(s)
        elif sym == window.K_LEFT: self._move(-1)
        elif sym == window.K_RIGHT: self._move(1)
        elif sym == window.K_UP: self._move(-COLS)
        elif sym == window.K_DOWN: self._move(COLS)
        elif sym == 0x4000004B: self._move(-COLS * ROWS)
        elif sym == 0x4000004E: self._move(COLS * ROWS)
        elif sym == window.K_BACKSPACE: self.filter = self.filter[:-1]; self.cursor = self.first = 0
        return True

    def typed(self, ch):
        if ch.lower() == "f" and time.time() - self.opened_at < 0.15: return
        self.filter = (self.filter + ch)[:40]; self.cursor = self.first = 0

    def wheel(self, dy):
        rows = self.shown() or []; self.first = max(0, min(max(0, (len(rows) - 1) // COLS * COLS), self.first - dy * COLS))

    GRID = (232, 76)
    BUTTONS = {"done": (28, 380, 90, 24), "cancel": (126, 380, 90, 24)}

    def click(self, x, y, s):
        """Mouse press at logical (x, y). Returns True if the window used it."""
        if not self.open: return False
        for name, (bx, by, bw, bh) in self.BUTTONS.items():
            if bx <= x < bx + bw and by <= y < by + bh:
                if name == "done": self.done(s)
                else: self.open = False
                return True
        for i, (kind, _) in enumerate(KINDS):
            if 232 + i * 110 <= x < 232 + i * 110 + 104 and 26 <= y < 46: self.tab = kind; self.filter = ""; self._focus(s); return True
        gx, gy = self.GRID; rows = self.shown() or []
        if gx <= x < gx + COLS * CELL and gy <= y < gy + ROWS * CELL:
            i = self.first + int((y - gy) // CELL) * COLS + int((x - gx) // CELL)
            if 0 <= i < len(rows): self.cursor = i; self.chosen[self.tab] = rows[i]
        return True

    def _thumb(self, kind, name, props):
        out = Image.new("RGBA", (CELL - 6, CELL - 6), (0, 0, 0, 0))
        if kind == "heads":
            im = render.load_image(name)
            if im is not None: top = 64 if im.height >= 96 else 0; out.alpha_composite(im.crop((0, top, min(32, im.width), min(top + 32, im.height))), (8, 8))
        else:
            if render.load_image(name) is not None: render.draw_character(out, "idle", 2, dict(props, BODYIMAGE=name), 8, 8)
        return out

    def draw(self, canvas, s):
        if not self.open: return
        w, h = canvas.size; d = ImageDraw.Draw(canvas, "RGBA")
        d.rectangle((8, 8, w - 8, h - 8), fill=BG, outline=EDGE, width=2)
        d.text((20, 14), "Choose how you look", fill=HOT); d.text((w - 250, 14), "Tab = heads / bodies   Esc = cancel", fill=DIM)
        props = dict(s.me); props["HEADIMAGE"] = self.chosen["heads"] or props.get("HEADIMAGE"); props["BODYIMAGE"] = self.chosen["bodies"] or props.get("BODYIMAGE")
        box = Image.new("RGBA", (64, 72), (40, 70, 44, 255)); render.draw_character(box, "idle", 2, props, 16, 26, 0.0)
        canvas.alpha_composite(box.resize((192, 216), Image.NEAREST), (28, 50))
        d.text((28, 270), "Head: " + (self.chosen["heads"] or "(unchanged)")[:34], fill=TEXT); d.text((28, 284), "Body: " + (self.chosen["bodies"] or "(unchanged)")[:34], fill=TEXT)
        for name, (bx, by, bw, bh) in self.BUTTONS.items():
            d.rectangle((bx, by, bx + bw, by + bh), fill=(50, 115, 55, 255) if name == "done" else (70, 78, 98, 255), outline=EDGE); d.text((bx + 28, by + 7), name.capitalize(), fill=TEXT)
        for i, (kind, label) in enumerate(KINDS):
            on = self.tab == kind; x = 232 + i * 110; n = self.names.get(kind)
            d.rectangle((x, 26, x + 104, 46), fill=(250, 250, 244, 255) if on else (60, 70, 90, 255), outline=EDGE if on else DIM)
            d.text((x + 6, 32), "%s%s" % (label, " (%d)" % len(n) if n is not None else ""), fill=(20, 20, 20, 255) if on else TEXT)
        d.text((232, 52), "Filter: " + self.filter + "_", fill=TEXT)
        rows = self.shown(); gx, gy = self.GRID
        if rows is None: d.text((gx, gy + 10), "Loading the list from the server ...", fill=DIM); return
        if not rows:
            d.text((gx, gy + 10), "Nothing found. " + ("Press Enter to use '%s' as the file name." % self.filter if self.filter else "The server has no list."), fill=DIM); return
        for k, name in enumerate(rows[self.first:self.first + COLS * ROWS]):
            i = self.first + k; x, y = gx + k % COLS * CELL, gy + k // COLS * CELL; sel = name.lower() == self.chosen[self.tab].lower()
            d.rectangle((x, y, x + CELL - 4, y + CELL - 4), fill=(60, 66, 88, 255), outline=HOT if sel else (90, 96, 118, 255), width=2 if sel else 1)
            canvas.alpha_composite(self._thumb(self.tab, name, props), (x + 1, y + 1))
        hover = rows[self.cursor] if 0 <= self.cursor < len(rows) else ""
        d.text((gx, gy + ROWS * CELL + 6), "%d of %d   %s" % (self.cursor + 1, len(rows), hover[:48]), fill=DIM)
        if self.status: d.text((gx, gy + ROWS * CELL + 20), self.status, fill=HOT)
