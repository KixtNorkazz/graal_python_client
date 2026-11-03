"""Player list (F7) and private messages: who is online on the server, send a PM with Enter, read the received ones.
F7 opens the list in a window of its own, which can be moved next to (or away from) the game window.

The game server sends every online player as PLO_OTHERPLPROPS when you log in and when they log in; a player who leaves the server is announced with the
DISCONNECT prop. `Session.online` holds them. Pure logic plus `draw()`; the viewer feeds it keys."""
import time
from PIL import Image, ImageDraw
import window

PANEL = (16, 16, 420)
WINDOW_PANEL, WINDOW_SIZE = (4, 4, 452), (460, 310)
ROW_H, MAX_ROWS, LOG_LINES, TOAST_SECS, DOUBLE_CLICK = 16, 10, 5, 6.0, 0.45
K_F7 = 0x40000040

def wrap(text, width):
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + (1 if line else 0) > width and line: out.append(line); line = word
        else: line = (line + " " + word) if line else word
    return out + ([line] if line else [])

class PlayerList:
    def __init__(self): self.win = None; self.panel = PANEL; self.open = False; self.cursor = 0; self.compose = False; self.text = ""; self.status = ""; self.seen_pms = 0; self._last_row, self._last_click = -1, 0.0

    def toggle(self, s, main=None):
        """Open or close the list. With the game window `main` it opens a window of its own beside it."""
        self.open = not self.open; self.compose = False; self.text = ""; self.status = ""
        if self.open:
            self.cursor = min(self.cursor, max(0, len(s.online_players()) - 1)); self.seen_pms = len(s.pm_log)
            if main is not None and self.win is None:
                self.win = window.Window("Players", *WINDOW_SIZE, secondary=True); self.win.place_beside(main); self.panel = WINDOW_PANEL
        else: self.close_window()

    def close_window(self):
        if self.win is not None: self.win.close(); self.win = None
        self.panel = PANEL

    def pump(self, s):
        """Handle what happened in the list window and show it again. Call once per frame of the game."""
        if self.win is None: return
        for ev in self.win.events():
            if ev[0] == "quit": self.toggle(s); return
            if ev[0] == "mousedown" and ev[1] == 1: self.click(ev[2], ev[3], s)
            elif ev[0] == "down" or (ev[0] == "repeat" and self.compose and ev[1] == window.K_BACKSPACE): self.key(ev[1], s)
            elif ev[0] == "text": self.typed(ev[1])
            elif ev[0] == "wheel":
                rows = s.online_players()
                if rows and not self.compose: self.cursor = max(0, min(len(rows) - 1, self.cursor - ev[1]))
            if self.win is None: return
        img = Image.new("RGBA", WINDOW_SIZE, (14, 18, 30, 255)); self.draw_panel(img, s); self.win.present(img.tobytes())
        self.win.title("Players online: %d" % len(s.online_players()))

    def key(self, sym, s):
        """A key while the list is open. Returns True if used."""
        rows = s.online_players()
        if self.compose:
            if sym == window.K_RETURN:
                if self.text.strip() and rows:
                    ok, why = s.send_pm([rows[self.cursor]["id"]], self.text)
                    if ok: self.compose, self.text, self.status = False, "", ""
                    else: self.status = why
                else: self.compose = False
            elif sym == window.K_ESCAPE: self.compose, self.text, self.status = False, "", ""
            elif sym == window.K_BACKSPACE: self.text = self.text[:-1]
            return True
        if sym in (K_F7, window.K_ESCAPE): self.toggle(s)
        elif sym == window.K_UP and rows: self.cursor = (self.cursor - 1) % len(rows)
        elif sym == window.K_DOWN and rows: self.cursor = (self.cursor + 1) % len(rows)
        elif sym == window.K_RETURN and rows: self.compose, self.text, self.status = True, "", ""
        return True

    def _first(self, n): return max(0, min(self.cursor - MAX_ROWS // 2, n - MAX_ROWS))

    def click(self, x, y, s, now=None):
        """Mouse press at logical (x, y): one click on a player selects, a double click starts a message. Returns True if the list used the click."""
        if not self.open: return False
        now = time.time() if now is None else now; rows = s.online_players(); px, py, pw = self.panel; first = self._first(len(rows))
        n = min(len(rows) - first, MAX_ROWS); y0 = py + 26
        if px <= x < px + pw and y0 <= y < y0 + n * ROW_H and not self.compose:
            i = first + int((y - y0) // ROW_H)
            if i == self.cursor and i == self._last_row and now - self._last_click < DOUBLE_CLICK: self.compose, self.text, self.status = True, "", ""
            self.cursor, self._last_row, self._last_click = i, i, now
            return True
        return px <= x < px + pw and py <= y < py + 140

    def typed(self, ch):
        if self.compose: self.text = (self.text + ch)[:200]

    def draw(self, out, s):
        """In the game window: the notice of a received message while the list is closed (and the list itself when it has no window of its own)."""
        if self.open:
            if self.win is None: self.draw_panel(out, s)
            return
        d = ImageDraw.Draw(out, "RGBA")
        if not self.open:
            new = s.pm_log[self.seen_pms:] if self.seen_pms <= len(s.pm_log) else []
            inc = [m for m in new if m["dir"] == "in"]
            if inc and time.time() - inc[-1]["t"] < TOAST_SECS:
                m = inc[-1]; lines = wrap(f"PM from {m['who']}: {m['text']}", 70)[:3]
                h = 8 + 12 * len(lines); x, y = 16, out.size[1] - 40 - h
                d.rectangle((x, y, x + 440, y + h), fill=(20, 24, 40, 225), outline=(240, 220, 130, 255), width=2)
                for i, l in enumerate(lines): d.text((x + 6, y + 4 + 12 * i), l, fill=(255, 255, 255, 255))
                d.text((x + 6, y - 12), "F7 = player list", fill=(230, 230, 200, 255))
            return

    def draw_panel(self, out, s):
        d = ImageDraw.Draw(out, "RGBA")
        rows = s.online_players(); px, py, pw = self.panel
        first = self._first(len(rows)); shown = rows[first:][:MAX_ROWS]
        log = s.pm_log[-LOG_LINES:]; log_lines = []
        for m in log: log_lines += wrap(("> " if m["dir"] == "out" else "") + f"{m['who']}: {m['text']}", 66)[:2]
        log_lines = log_lines[-LOG_LINES:]
        h = 30 + max(1, len(shown)) * ROW_H + 18 + 12 * max(1, len(log_lines)) + 30
        d.rectangle((px, py, px + pw, py + h), fill=(20, 24, 40, 225), outline=(240, 220, 130, 255), width=2)
        d.text((px + 8, py + 8), f"Players online: {len(rows)}   (click = choose, double-click or Enter = PM, Esc = close)", fill=(255, 255, 255, 255))
        y = py + 26
        if not rows: d.text((px + 8, y + 2), "(nobody else is online)", fill=(200, 200, 200, 255))
        for i, p in enumerate(shown):
            sel = first + i == self.cursor
            if sel: d.rectangle((px + 4, y, px + pw - 4, y + ROW_H - 2), fill=(250, 250, 244, 255))
            col = (20, 20, 20, 255) if sel else (235, 235, 215, 255)
            d.text((px + 8, y + 2), (p["nick"] or p["account"])[:26], fill=col)
            d.text((px + 190, y + 2), p["account"][:14], fill=col); d.text((px + 290, y + 2), p["level"][:20], fill=col)
            y += ROW_H
        y = py + 30 + max(1, len(shown)) * ROW_H
        d.line((px + 4, y, px + pw - 4, y), fill=(240, 220, 130, 160))
        for i, l in enumerate(log_lines or ["(no messages yet)"]): d.text((px + 8, y + 6 + 12 * i), l, fill=(210, 230, 255, 255))
        y += 12 + 12 * max(1, len(log_lines)) + 4
        if self.compose and rows:
            who = rows[self.cursor]; d.text((px + 8, y + 2), f"To {who['nick'] or who['account']}: {self.text[-48:]}_", fill=(255, 240, 160, 255))
            if self.status: d.text((px + 8, y + 14), self.status, fill=(255, 150, 130, 255))
