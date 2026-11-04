"""Guilds (G on a PC, Menu > Guild on the phone): the guilds you are in, your rank, the members, and wearing a guild tag in your nickname.

Membership lives on the server (guilds/guild<Name>.txt); the patched gs2emu answers the gr.guild trigger commands and checks every change:
an officer can add and remove plain members, a leader can also make members officers or leaders, and a guild always keeps one leader.
This window only shows what the server sent (Session.guilds) and asks it (Session.guild_cmd, Session.set_guild_tag). Pure logic plus draw();
the viewer and the Android app feed it keys, typed text and clicks."""
import time
from PIL import ImageDraw
import render, uitext

K_G = ord("g")
PANEL = (80, 36, 480)   # x, y, width (logical 640x480; the phone centres it)
ROWS = 7                # member rows shown at once
ROW_H = 22
RANK_NAMES = ("Member", "Officer", "Leader")
CONFIRM_SECS = 3.0      # leave / remove need a second press within this time
MAX_NAME = 60


class GuildWindow:
    def __init__(self):
        self.open = False; self.gi = 0; self.cursor = 0; self.first = 0; self.typing = False; self.text = ""; self.panel = PANEL
        self.confirm = None   # (key, guild, account, time) of a leave / remove waiting for its second press
        self.naming = ""      # the account whose name is being typed (typing == "name")

    # ---- state -------------------------------------------------------------------------------------------------------------------------
    def toggle(self, s):
        self.open = not self.open; self.typing = False; self.confirm = None
        if self.open: s.guild_cmd("info")   # fresh list every time it opens

    def guild(self, s):
        gs = getattr(s, "guilds", None) or []
        if not gs: return None
        self.gi = max(0, min(self.gi, len(gs) - 1)); return gs[self.gi]

    def member(self, s):
        g = self.guild(s)
        if not g or not g["members"]: return None
        self.cursor = max(0, min(self.cursor, len(g["members"]) - 1)); return g["members"][self.cursor]

    def buttons(self, s):
        """(key, label) of the buttons for your rank in the shown guild: everyone can wear the tag and leave; officers add and remove; leaders set ranks."""
        g = self.guild(s)
        if not g: return [], []
        row1 = [("wear", "Wear tag"), ("untag", "Remove tag"), ("leave", "Leave")]
        row2 = []
        if g["rank"] >= 1: row2 += [("add", "Add"), ("remove", "Remove"), ("name", "Name")]
        if g["rank"] >= 2: row2 += [("officer", "Officer"), ("member", "Member"), ("leader", "Leader")]
        return row1, row2

    # ---- actions -----------------------------------------------------------------------------------------------------------------------
    def act(self, key, s, now=None):
        now = time.time() if now is None else now
        g = self.guild(s)
        if not g: return
        name = g["name"]; m = self.member(s); acc = m[0] if m else ""
        if key == "wear": s.set_guild_tag(name)
        elif key == "untag": s.set_guild_tag("")
        elif key == "add": self.typing = "add"; self.text = ""
        elif key == "name" and acc: self.typing = "name"; self.text = m[2] if len(m) > 2 else ""; self.naming = acc
        elif key in ("leave", "remove"):
            target = getattr(s, "account_name", "") if key == "leave" else acc
            if not target: return
            c = self.confirm
            if c and c[:3] == (key, name, target) and now - c[3] <= CONFIRM_SECS:
                self.confirm = None
                if key == "leave": s.guild_cmd("leave", name)
                else: s.guild_cmd("remove", name, target)
            else: self.confirm = (key, name, target, now)
        elif key in ("officer", "member", "leader") and acc: s.guild_cmd("rank", name, acc, key)

    def submit(self, s):
        """Enter in the text field. Add: "Account" or "Account:Name" (the one name the account may wear with the tag). Name: the name ("" = any)."""
        g = self.guild(s); text = self.text.strip(); mode = self.typing; self.typing = False; self.text = ""
        if not g: return
        if mode == "add" and text:
            acc, _, nick = text.partition(":")
            if acc.strip(): s.guild_cmd("add", g["name"], acc.strip(), *([nick.strip()] if nick.strip() else []))
        elif mode == "name" and getattr(self, "naming", ""): s.guild_cmd("nick", g["name"], self.naming, text)

    def key(self, sym, s):
        """A key while the window is open (SDL keysyms). Returns True if used."""
        import window
        if self.typing:
            if sym == window.K_RETURN: self.submit(s)
            elif sym == window.K_ESCAPE: self.typing = False; self.text = ""
            elif sym == window.K_BACKSPACE: self.text = self.text[:-1]
            return True
        g = self.guild(s); n = len(g["members"]) if g else 0
        if sym in (window.K_ESCAPE, K_G): self.open = False
        elif sym == window.K_LEFT: self.gi = max(0, self.gi - 1); self.cursor = self.first = 0
        elif sym == window.K_RIGHT: self.gi = min(len(getattr(s, "guilds", None) or [1]) - 1, self.gi + 1); self.cursor = self.first = 0
        elif sym == window.K_UP and n: self.cursor = (self.cursor - 1) % n
        elif sym == window.K_DOWN and n: self.cursor = (self.cursor + 1) % n
        elif sym == window.K_RETURN: self.act("wear", s)
        self._scroll(n)
        return True

    def typed(self, ch):
        if self.typing and len(self.text) < MAX_NAME and ch.isprintable() and ch not in "()" and (ch != ":" or self.typing == "add"): self.text += ch

    def _scroll(self, n):
        if self.cursor < self.first: self.first = self.cursor
        elif self.cursor >= self.first + ROWS: self.first = self.cursor - ROWS + 1
        self.first = max(0, min(self.first, max(0, n - ROWS)))

    # ---- layout ------------------------------------------------------------------------------------------------------------------------
    def _height(self): return 112 + ROWS * ROW_H + 126

    def _boxes(self, s):
        """Where things are: the < > arrows, the member rows, the buttons, the close box."""
        px, py, pw = self.panel; h = self._height(); out = {}
        out["prev"] = (px + 10, py + 64, px + 40, py + 88); out["next"] = (px + pw - 40, py + 64, px + pw - 10, py + 88)
        out["rows"] = [(px + 10, py + 112 + i * ROW_H, px + pw - 10, py + 112 + (i + 1) * ROW_H) for i in range(ROWS)]
        row1, row2 = self.buttons(s); y1 = py + 116 + ROWS * ROW_H; y2 = y1 + 32
        for row, y in ((row1, y1), (row2, y2)):
            if not row: continue
            bw = min(110, (pw - 20) // len(row) - 6); x = px + (pw - len(row) * (bw + 6)) // 2
            for k, label in row: out[k] = (x, y, x + bw, y + 26); x += bw + 6
        out["close"] = (px + pw // 2 - 40, py + h - 30, px + pw // 2 + 40, py + h - 6)
        return out

    def click(self, x, y, s, now=None):
        """Press at logical (x, y). Returns True if the window used it."""
        if not self.open: return False
        px, py, pw = self.panel; h = self._height(); b = self._boxes(s)
        def inside(box): return box[0] <= x < box[2] and box[1] <= y < box[3]
        if inside(b["close"]): self.open = False; return True
        if inside(b["prev"]): self.gi = max(0, self.gi - 1); self.cursor = self.first = 0; return True
        if inside(b["next"]): self.gi = min(len(getattr(s, "guilds", None) or [1]) - 1, self.gi + 1); self.cursor = self.first = 0; return True
        g = self.guild(s)
        for i, box in enumerate(b["rows"]):
            if inside(box) and g and self.first + i < len(g["members"]): self.cursor = self.first + i; return True
        for k in ("wear", "untag", "leave", "add", "remove", "name", "officer", "member", "leader"):
            if k in b and inside(b[k]): self.act(k, s, now); return True
        return px <= x < px + pw and py <= y < py + h

    # ---- drawing -----------------------------------------------------------------------------------------------------------------------
    def status(self, s, now=None):
        """The line under the buttons: what you are typing, a confirmation to give, or the server's last answer."""
        now = time.time() if now is None else now
        if self.typing == "add": return f"Add (Account or Account:Name): {self.text}_"
        if self.typing: return f"Name for {getattr(self, 'naming', '')}: {self.text}_   (empty = any name)"
        c = self.confirm
        if c and now - c[3] <= CONFIRM_SECS:
            return f"Press Leave again to leave {c[1]}" if c[0] == "leave" else f"Press Remove again to remove {c[2]} from {c[1]}"
        msg = getattr(s, "guild_message", None)
        if msg and now - msg[1] < 10: return msg[0]
        return ""

    def draw(self, out, s, hint=None):
        if not self.open: return
        px, py, pw = self.panel; h = self._height(); b = self._boxes(s)
        d = ImageDraw.Draw(out, "RGBA")
        d.rectangle((px, py, px + pw, py + h), fill=(20, 24, 40, 235), outline=(240, 220, 130, 255), width=2)
        def left(text, x, y): render.draw_chat(out, text, x + len(text) * 3, y)
        render.draw_chat(out, "Guilds", px + pw // 2, py + 20)
        tag = getattr(s, "guild", "")
        left(f"Your nickname: {s.me.get('NICKNAME', '')}" + ("" if tag else "   (no guild tag)"), px + 12, py + 46)
        g = self.guild(s); gs = getattr(s, "guilds", None) or []
        if not g:
            render.draw_chat(out, "You are not in a guild." if gs == [] and hasattr(s, "guilds") else "Asking the server ...", px + pw // 2, py + 120)
            render.draw_chat(out, "A leader or officer of a guild can add you.", px + pw // 2, py + 142)
        else:
            for k, sign in (("prev", "<"), ("next", ">")):
                box = b[k]; on = (k == "prev" and self.gi > 0) or (k == "next" and self.gi < len(gs) - 1)
                d.rectangle(box, fill=(60, 70, 110, 255) if on else (40, 44, 60, 255), outline=(240, 220, 130, 255))
                render.draw_chat(out, sign, (box[0] + box[2]) // 2, box[3] - 6)
            render.draw_chat(out, f"{g['name']}   ({RANK_NAMES[max(0, min(2, g['rank']))]})   {self.gi + 1}/{len(gs)}", px + pw // 2, py + 82)
            left(f"{len(g['members'])} members", px + 14, py + 104)
            for i, box in enumerate(b["rows"]):
                j = self.first + i
                if j >= len(g["members"]): break
                acc, rank = g["members"][j][:2]; nick = g["members"][j][2] if len(g["members"][j]) > 2 else ""
                if j == self.cursor: d.rectangle(box, fill=(70, 90, 150, 200))
                left(acc, box[0] + 6, box[3] - 6); render.draw_chat(out, RANK_NAMES[max(0, min(2, rank))], box[2] - 50, box[3] - 6)
                if nick: left(nick if len(nick) <= 44 else nick[:42] + "..", box[0] + 112, box[3] - 6)
            row1, row2 = self.buttons(s)
            for k, label in row1 + row2:
                box = b[k]; d.rectangle(box, fill=(60, 70, 110, 255), outline=(240, 220, 130, 255))
                render.draw_chat(out, label, (box[0] + box[2]) // 2, box[3] - 7)
        st = self.status(s)
        if st: render.draw_chat(out, st, px + pw // 2, py + h - 42)
        cb = b["close"]; d.rectangle(cb, fill=(60, 70, 110, 255), outline=(240, 220, 130, 255))
        render.draw_chat(out, "Close", (cb[0] + cb[2]) // 2, cb[3] - 6)
        hint = uitext.t("guild_help") if hint is None else hint
        if hint: render.draw_chat(out, hint, px + pw // 2, py + h + 14)
