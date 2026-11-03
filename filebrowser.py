"""A file browser dialog for the level editor: folders and files, a name field, optional image preview.

FileBrowser(title, folder, exts=(".nw",), save=False, name="")      browse real folders; save=True adds a file name that is saved under
FileBrowser(title, None, exts, flat=[(label, path), ...], preview=True)   pick from a ready made list (for example every image the client knows)

`handle(event, mod)` takes the events of window.Window and returns None while open, then ("ok", path) or ("cancel", None).
`draw(canvas)` paints it centred on a PIL image."""
import os, time
from PIL import Image, ImageDraw
import window

LINE_H, ROWS = 13, 24
BG, EDGE, TEXT, DIM, HOT, DIR = (20, 24, 40, 245), (240, 220, 130, 255), (255, 255, 255, 255), (170, 175, 190, 255), (255, 240, 160, 255), (150, 200, 255, 255)
SEL_BG, SEL_TEXT = (250, 250, 244, 255), (20, 20, 20, 255)
PAGE_UP, PAGE_DOWN = 0x4000004B, 0x4000004E
DOUBLE_CLICK = 0.5


class FileBrowser:
    def __init__(self, title, folder, exts=(), save=False, name="", flat=None, preview=False):
        self.title, self.exts, self.save, self.flat, self.preview = title, tuple(e.lower() for e in exts), save, flat, preview
        self.folder = os.path.abspath(folder) if folder else ""
        self.text = name; self.cursor = 0; self.first = 0; self.rows = []; self._thumb = (None, None); self._click = (None, 0); self._geom = None
        self._refresh()

    def _want(self, name): return not self.exts or os.path.splitext(name)[1].lower() in self.exts

    def _refresh(self):
        needle = "" if self.save else self.text.lower()
        if self.flat is not None:
            self.rows = [("file", label, path) for label, path in self.flat if needle in label.lower()]
        else:
            rows = []
            try: names = sorted(os.listdir(self.folder), key=str.lower)
            except OSError: names = []
            parent = os.path.dirname(self.folder)
            if parent != self.folder: rows.append(("dir", "..", parent))
            for n in names:
                full = os.path.join(self.folder, n)
                if not n.startswith(".") and os.path.isdir(full) and (not needle or needle in n.lower()): rows.append(("dir", n, full))
            for n in names:
                full = os.path.join(self.folder, n)
                if not n.startswith(".") and os.path.isfile(full) and self._want(n) and (not needle or needle in n.lower()): rows.append(("file", n, full))
            self.rows = rows
        self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
        if self.cursor == 0 and len(self.rows) > 1 and self.rows[0][1] == "..": self.cursor = 1
        self._scroll_to_cursor()

    def _scroll_to_cursor(self):
        if self.cursor < self.first: self.first = self.cursor
        elif self.cursor >= self.first + ROWS: self.first = self.cursor - ROWS + 1
        self.first = max(0, min(self.first, max(0, len(self.rows) - ROWS)))

    def _move(self, d):
        if self.rows: self.cursor = max(0, min(len(self.rows) - 1, self.cursor + d)); self._scroll_to_cursor(); self._pick_name()

    def _pick_name(self):
        if self.save and self.rows and self.rows[self.cursor][0] == "file": self.text = self.rows[self.cursor][1]

    def _enter_dir(self, path):
        if os.path.isdir(path): self.folder = path; self.text = "" if not self.save else self.text; self.cursor = self.first = 0; self._refresh()

    def _accept(self):
        if self.save:
            name = self.text.strip()
            if not name:
                return self._activate_row()
            full = os.path.join(self.folder, name)
            if os.path.isdir(full): self._enter_dir(full); self.text = ""; return None
            if self.exts and not os.path.splitext(name)[1]: full += self.exts[0]
            return ("ok", full) if os.path.basename(full) not in ("", ".", "..") else None
        return self._activate_row()

    def _activate_row(self):
        if not self.rows:
            return ("ok", os.path.join(self.folder, self.text)) if self.text and self.flat is not None else None
        kind, _, path = self.rows[self.cursor]
        if kind == "dir": self._enter_dir(path); return None
        return ("ok", path)

    def handle(self, ev, mod=0):
        if ev[0] == "text":
            self.text += ev[1]; self.cursor = self.first = 0; self._refresh()
        elif ev[0] == "wheel":
            self.first = max(0, min(self.first - ev[1] * 3, max(0, len(self.rows) - ROWS)))
        elif ev[0] == "down":
            k = ev[1]
            if k == window.K_ESCAPE: return ("cancel", None)
            if k == window.K_BACKSPACE:
                if self.text: self.text = self.text[:-1]; self.cursor = self.first = 0; self._refresh()
                elif not self.flat and self.rows and self.rows[0][1] == "..": self._enter_dir(self.rows[0][2])
            elif k == window.K_DOWN: self._move(1)
            elif k == window.K_UP: self._move(-1)
            elif k == PAGE_DOWN: self._move(ROWS - 1)
            elif k == PAGE_UP: self._move(-(ROWS - 1))
            elif k == window.K_RETURN: return self._accept()
        elif ev[0] == "mousedown" and ev[1] == 1 and self._geom:
            x, y = ev[2], ev[3]; gx, gy, gw, list_y, bx = self._geom
            i = int((y - list_y) // LINE_H) + self.first
            if gx <= x < gx + gw and list_y <= y < list_y + ROWS * LINE_H and 0 <= i < len(self.rows):
                now = time.monotonic(); again = self._click[0] == i and now - self._click[1] < DOUBLE_CLICK
                self.cursor = i; self._click = (i, now); self._pick_name()
                if again: return self._activate_row()
            elif bx and bx[0][0] <= x < bx[0][0] + bx[0][2] and bx[0][1] <= y < bx[0][1] + 16: return self._accept()
            elif bx and bx[1][0] <= x < bx[1][0] + bx[1][2] and bx[1][1] <= y < bx[1][1] + 16: return ("cancel", None)
        return None

    def _preview_image(self):
        if not self.rows or self.rows[self.cursor][0] != "file": return None
        path = self.rows[self.cursor][2]
        if self._thumb[0] != path:
            try:
                with Image.open(path) as im: im = im.convert("RGBA"); im.thumbnail((220, 220), Image.NEAREST if max(im.size) < 220 else Image.BILINEAR)
            except Exception: im = None
            self._thumb = (path, im)
        return self._thumb[1]

    def draw(self, canvas):
        d = ImageDraw.Draw(canvas, "RGBA"); lw = 420; pw = 240 if self.preview else 0; w = lw + pw + 20
        h = 82 + ROWS * LINE_H + 34; x0, y0 = (canvas.size[0] - w) // 2, max(6, (canvas.size[1] - h) // 2)
        d.rectangle((x0, y0, x0 + w, y0 + h), fill=BG, outline=EDGE, width=2)
        d.text((x0 + 10, y0 + 8), self.title, fill=HOT)
        where = self.folder if self.flat is None else "%d files" % len(self.rows)
        d.text((x0 + 10, y0 + 22), ("..." + where[-(lw // 6 - 3):]) if len(where) > lw // 6 else where, fill=DIM)
        label = "File name: " if self.save else "Filter: "
        d.rectangle((x0 + 10, y0 + 38, x0 + lw, y0 + 54), fill=(250, 250, 244, 255), outline=EDGE)
        d.text((x0 + 14, y0 + 42), label + self.text[-(lw // 6 - len(label) - 2):] + "_", fill=SEL_TEXT)
        list_y = y0 + 62
        for i, (kind, name, _) in enumerate(self.rows[self.first:self.first + ROWS]):
            y = list_y + i * LINE_H; sel = self.first + i == self.cursor
            if sel: d.rectangle((x0 + 6, y, x0 + lw, y + LINE_H - 1), fill=SEL_BG)
            d.text((x0 + 10, y + 1), ("[%s]" % name if kind == "dir" else name)[:lw // 6 - 2], fill=SEL_TEXT if sel else DIR if kind == "dir" else TEXT)
        if not self.rows: d.text((x0 + 10, list_y + 2), "(nothing here)" if not self.text else "(nothing matches)", fill=DIM)
        if len(self.rows) > ROWS:
            th = max(10, ROWS * LINE_H * ROWS // len(self.rows)); ty = list_y + (ROWS * LINE_H - th) * self.first // max(1, len(self.rows) - ROWS)
            d.rectangle((x0 + lw + 2, list_y, x0 + lw + 6, list_y + ROWS * LINE_H), fill=(50, 56, 80, 255)); d.rectangle((x0 + lw + 2, ty, x0 + lw + 6, ty + th), fill=EDGE)
        if self.preview:
            px = x0 + lw + 14; d.rectangle((px, list_y, px + 224, list_y + 224), outline=DIM)
            im = self._preview_image()
            if im is not None:
                tile = Image.new("RGBA", im.size, (60, 66, 88, 255)); tile.alpha_composite(im); canvas.paste(tile, (px + 2, list_y + 2))
                d.text((px, list_y + 230), "%s  %d x %d" % (os.path.basename(self.rows[self.cursor][2])[:24], *self._full_size()), fill=DIM)
        by = y0 + h - 24; ok = (x0 + 10, by, 70); cancel = (x0 + 90, by, 70)
        for (bx_, by_, bw), text in ((ok, "Save" if self.save else "Open"), (cancel, "Cancel")):
            d.rectangle((bx_, by_, bx_ + bw, by_ + 16), fill=(60, 70, 66, 255), outline=EDGE); d.text((bx_ + 8, by_ + 4), text, fill=TEXT)
        d.text((x0 + 176, by + 4), "Enter = " + ("save" if self.save else "open") + "   Esc = cancel   Backspace = folder up", fill=DIM)
        self._geom = (x0, y0, lw, list_y, ((ok[0], ok[1], ok[2]), (cancel[0], cancel[1], cancel[2])))

    def _full_size(self):
        try:
            with Image.open(self.rows[self.cursor][2]) as im: return im.size
        except Exception: return (0, 0)
