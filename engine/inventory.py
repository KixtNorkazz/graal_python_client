"""The inventory list (Q): choose the active weapon. D fires it (the weapon's own `weaponfired` script decides what that means: GreenDragon mounts / lands the dragon),
S is the sword as always (weapons hear `playershootssword`: the mounted dragon attacks).

Pure logic plus `draw()`; the viewer feeds it keys and clicks. The weapons come from `session.runner.firable()` (the ones with a `weaponfired` event), in the order
the server sent them. Digits 1-9 pick the n-th weapon directly."""
from PIL import Image, ImageDraw
import render

ROW_H, PANEL = 20, (16, 16, 330)
STATS = (("GRALATS", "Rupees"), ("BOMBS", "Bombs"), ("ARROWS", "Arrows"), ("GLOVEPOWER", "Glove"), ("SWORDPOWER", "Sword"), ("SHIELDPOWER", "Shield"))

class Inventory:
    def __init__(self): self.open = False; self.cursor = 0; self.active = None

    def weapons(self, s): return s.runner.firable()

    def toggle(self, s):
        self.open = not self.open
        if self.open:
            names = [w.name for w in self.weapons(s)]; self.cursor = names.index(self.active) if self.active in names else 0

    def choose(self, s, index=None):
        """Make the weapon at `index` (default: the cursor) the active one. Returns its name or None."""
        ws = self.weapons(s); i = self.cursor if index is None else index
        if not 0 <= i < len(ws): return None
        self.cursor = i; self.active = ws[i].name; s.runner.selected = self.active; return self.active

    def fire(self, s):
        """D: run `weaponfired` of the active weapon. Returns its name, or None (no active weapon / it is gone / weapons are disabled)."""
        ws = self.weapons(s); s.runner.selected = self.active
        for i, w in enumerate(ws):
            if w.name == self.active: return s.runner.fire(i)
        return None

    def key(self, sym, s):
        """A key while the list is open (SDL keysyms). Returns True if used."""
        import window
        n = len(self.weapons(s))
        if sym == window.K_UP and n: self.cursor = (self.cursor - 1) % n
        elif sym == window.K_DOWN and n: self.cursor = (self.cursor + 1) % n
        elif sym == window.K_RETURN: self.choose(s); self.open = False
        elif sym in (window.K_ESCAPE, ord("q")): self.open = False
        elif sym == ord("d"): self.fire(s); self.open = False
        elif ord("1") <= sym <= ord("9"): self.choose(s, sym - ord("1"))
        return True

    def click(self, x, y, s):
        """Mouse press at logical (x, y): a row picks that weapon. Returns True if the list used the click."""
        px, py, pw = PANEL
        if not self.open: return False
        ws = self.weapons(s); y0 = py + 28 + len(STATS) * 0 + self._stats_h(s)
        if px <= x < px + pw and y >= y0:
            i = int((y - y0) // ROW_H)
            if i < len(ws): self.choose(s, i); self.open = False
        return px <= x < px + pw and py <= y < y0 + max(1, len(ws)) * ROW_H + 8

    def _stats_h(self, s): return 16 * ((len(self._stat_lines(s)) + 1) // 2) + 8

    def _stat_lines(self, s):
        out = []
        for key, label in STATS:
            v = s.me.get(key)
            if v not in (None, "", 0, 0.0) or key in ("GRALATS", "BOMBS", "ARROWS"): out.append(f"{label}: {int(float(v or 0))}")
        return out

    def status(self, s):
        """Text for the HUD line."""
        return f"Weapon: {self.active}  (D uses it, Q = inventory)" if self.active in [w.name for w in self.weapons(s)] else "Q: inventory"

    def draw(self, out, s):
        if not self.open: return
        px, py, pw = PANEL; ws = self.weapons(s); stats = self._stat_lines(s); sh = self._stats_h(s)
        h = 28 + sh + max(1, len(ws)) * ROW_H + 30
        d = ImageDraw.Draw(out, "RGBA"); d.rectangle((px, py, px + pw, py + h), fill=(20, 24, 40, 225), outline=(240, 220, 130, 255), width=2)
        render.draw_chat(out, "Inventory", px + pw // 2, py + 18)
        for k, line in enumerate(stats): render.draw_chat(out, line, px + 60 + (k % 2) * 140, py + 34 + (k // 2) * 16)
        y0 = py + 28 + sh
        if not ws: render.draw_chat(out, "(no weapons)", px + pw // 2, y0 + 16)
        for i, w in enumerate(ws):
            ry = y0 + i * ROW_H
            if i == self.cursor: d.rectangle((px + 4, ry, px + pw - 4, ry + ROW_H - 2), fill=(70, 90, 150, 200))
            im = render.load_image(w.image) if w.image else None
            if im is not None:
                ic = im.copy(); ic.thumbnail((16, 16)); out.alpha_composite(ic.convert("RGBA"), (px + 8, ry + 1))
            mark = ("* " if w.name == self.active else "  ") + (f"{i + 1}. " if i < 9 else "") + w.name
            render.draw_chat(out, mark, px + 30 + len(mark) * 3, ry + 16)
        render.draw_chat(out, "Enter = choose   D = use weapon   Q = close", px + pw // 2, py + h - 4)
