"""Login screen: Nickname, Account, Password and a Start button on top of logos-1.jpg (SDL2 window, drawn with Pillow).

`run(version, listserver, game_host)` shows the screen and returns a connected `Session` (or None when the window is closed). Start contacts the
list server (the same exchange as the real client: hello + account/password, the answer carries the server list and a welcome text), then logs in
at the game server you pick from the list and tells it the nickname (player prop 0, which the real client sends in its first props line).
The nickname and account are remembered in `login.json` (never the password)."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
import window

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "logos-1.jpg"); SAVED = os.path.join(HERE, "login.json")
W, IMG_H, H = 640, 429, 650
K_TAB = 9
FIELDS = [("nick", "Nickname:", False), ("account", "Account:", False), ("password", "Password:", True)]
FX, FW, FH, FY0, FSTEP = 232, 300, 26, 446, 38
ROW_H, MAX_ROWS = 24, 4
BTN = (240, 568, 160, 38)
BUILD_BTN = (420, 568, 100, 38)

def _font(): return ImageFont.load_default()

def text_img(txt, color, scale=2, font=None):
    """Text in the default bitmap font, enlarged `scale` times (nearest neighbour keeps it crisp); this Pillow has no FreeType."""
    font = font or _font(); l, t, r, b = font.getbbox(txt or " "); w, h = max(1, r), max(1, b + 2)
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).text((0, 0), txt, fill=255, font=font)
    m = m.resize((w * scale, h * scale), Image.NEAREST); im = Image.new("RGBA", m.size, color + (0,) if len(color) == 3 else color); im.putalpha(m); return im

def load_saved():
    try: return json.load(open(SAVED, encoding="utf-8"))
    except (OSError, ValueError): return {}

def save_saved(d):
    try: json.dump({k: d.get(k, "") for k in ("nick", "account")}, open(SAVED, "w", encoding="utf-8"))
    except OSError: pass

class Screen:
    def __init__(self, saved=None):
        saved = saved or {}
        self.vals = {"nick": saved.get("nick", ""), "account": saved.get("account", ""), "password": os.environ.get("GRAAL_PASSWORD", "")}
        self.focus = "account" if self.vals["nick"] else "nick"
        if self.vals["nick"] and self.vals["account"]: self.focus = "password"
        self.status, self.status_color, self.busy = "", (230, 230, 230), False
        self.servers, self.sel, self.session = None, 0, None
        self.bg = self._background()

    def _background(self):
        bg = Image.new("RGBA", (W, H), (14, 46, 20, 255))
        try:
            logo = Image.open(LOGO).convert("RGB").resize((W, IMG_H), Image.LANCZOS)
            bg.paste(logo, (0, 0))
            edge = logo.crop((0, IMG_H - 6, W, IMG_H)).resize((1, 1), Image.BOX).getpixel((0, 0))
            ImageDraw.Draw(bg).rectangle((0, IMG_H, W, H), fill=tuple(max(0, c - 18) for c in edge) + (255,))
        except OSError: pass
        return bg

    def field_rect(self, k): i = [f[0] for f in FIELDS].index(k); return (FX, FY0 + i * FSTEP, FW, FH)

    def row_rect(self, i): return (FX - 100, FY0 + i * ROW_H, FW + 100, ROW_H - 2)

    def hit(self, x, y):
        if self.servers:
            for i in range(min(len(self.servers), MAX_ROWS)):
                rx, ry, rw, rh = self.row_rect(i)
                if rx <= x < rx + rw and ry <= y < ry + rh: return "row%d" % i
        else:
            for k, _, _ in FIELDS:
                fx, fy, fw, fh = self.field_rect(k)
                if fx <= x < fx + fw and fy <= y < fy + fh: return k
        bx, by, bw, bh = BTN
        if bx <= x < bx + bw and by <= y < by + bh: return "start"
        bx, by, bw, bh = BUILD_BTN
        return "build" if bx <= x < bx + bw and by <= y < by + bh else None

    def draw(self, now, hover=None):
        im = self.bg.copy(); d = ImageDraw.Draw(im, "RGBA")
        d.rectangle((0, IMG_H, W, IMG_H + 2), fill=(0, 0, 0, 90))
        if self.servers:
            for i, sv in enumerate(self.servers[:MAX_ROWS]):
                rx, ry, rw, rh = self.row_rect(i); sel = i == self.sel
                d.rectangle((rx, ry, rx + rw, ry + rh), fill=(250, 250, 244, 255) if sel else (30, 70, 35, 230), outline=(240, 220, 130, 255) if sel else (30, 70, 35, 255), width=2)
                col = (20, 20, 20) if sel else (235, 235, 215)
                im.alpha_composite(text_img(sv["name"][:34], col, scale=1), (rx + 6, ry + 6))
                info = ("%s players  %s" % (sv["players"], sv["language"])).strip()
                t = text_img(info, col, scale=1); im.alpha_composite(t, (rx + rw - t.width - 6, ry + 6))
        else:
            for k, label, secret in FIELDS:
                fx, fy, fw, fh = self.field_rect(k)
                im.alpha_composite(text_img(label, (235, 235, 215)), (FX - 112, fy + 4))
                d.rectangle((fx, fy, fx + fw, fy + fh), fill=(250, 250, 244, 255), outline=(240, 220, 130, 255) if k == self.focus else (30, 70, 35, 255), width=2)
                v = self.vals[k]; shown = "*" * len(v) if secret else v
                ti = text_img(shown[-22:], (20, 20, 20)); im.alpha_composite(ti, (fx + 6, fy + 4))
                if k == self.focus and int(now * 2) % 2 == 0 and not self.busy: d.rectangle((fx + 8 + ti.width - (0 if shown else 0), fy + 4, fx + 9 + ti.width, fy + fh - 5), fill=(20, 20, 20, 255))
        bx, by, bw, bh = BTN
        col = (70, 150, 70, 255) if hover == "start" and not self.busy else (50, 115, 55, 255)
        if self.busy: col = (80, 90, 80, 255)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=6, fill=col, outline=(240, 220, 130, 255), width=2)
        t = text_img("Logging in..." if self.busy else ("Join" if self.servers else "Start"), (255, 255, 255), scale=2)
        im.alpha_composite(t, (bx + (bw - t.width) // 2, by + (bh - t.height) // 2))
        bx, by, bw, bh = BUILD_BTN
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=6, fill=(60, 80, 110, 255) if hover == "build" else (45, 62, 88, 255), outline=(240, 220, 130, 255), width=2)
        t = text_img("Build", (255, 255, 255), scale=2); im.alpha_composite(t, (bx + (bw - t.width) // 2, by + (bh - t.height) // 2))
        if self.status:
            for n, line in enumerate(self.status.split("\n")[:2]):
                t = text_img(line, self.status_color, scale=1); im.alpha_composite(t, ((W - t.width) // 2, BTN[1] + BTN[3] + 12 + n * 14))
        return im

    def key(self, sym):
        """Returns 'start' / 'quit' / None."""
        if self.busy: return None
        names = [f[0] for f in FIELDS]
        if self.servers:
            if sym == window.K_ESCAPE: self.servers = None; self.status = ""; return None
            if sym == window.K_DOWN: self.sel = (self.sel + 1) % min(len(self.servers), MAX_ROWS)
            elif sym == window.K_UP: self.sel = (self.sel - 1) % min(len(self.servers), MAX_ROWS)
            elif sym == window.K_RETURN: return "join"
            return None
        if sym == window.K_ESCAPE: return "quit"
        if sym == K_TAB or sym == window.K_DOWN: self.focus = names[(names.index(self.focus) + 1) % 3] if self.focus in names else names[0]
        elif sym == window.K_UP: self.focus = names[(names.index(self.focus) - 1) % 3] if self.focus in names else names[0]
        elif sym == window.K_BACKSPACE and self.focus in self.vals: self.vals[self.focus] = self.vals[self.focus][:-1]
        elif sym == window.K_RETURN:
            if self.focus == "password" or self.focus == "start": return "start"
            self.focus = names[names.index(self.focus) + 1]
        return None

    def typed(self, s):
        if self.servers: return
        if self.focus in self.vals and not self.busy: self.vals[self.focus] = (self.vals[self.focus] + s)[:30]

def contact(screen, win, version, listserver, game_host, verbose=False):
    """Start pressed: ask the list server for its servers and show them. Returns None; the screen then lists the servers."""
    from minclient import list_servers_full
    from gclient import Session
    acc, pw = screen.vals["account"].strip(), screen.vals["password"]
    if not acc or not pw:
        screen.status, screen.status_color = "Fill in Account and Password.", (255, 190, 120); return None
    screen.busy = True; screen.status, screen.status_color = "Contacting the server list...", (230, 230, 230)
    win.present(screen.draw(time.time()).tobytes())
    try:
        s = Session(acc, pw, version, listserver, game_host)
        servers, notes = list_servers_full(*s.listserver, s.account, s.password, False)
        if not servers:
            screen.status, screen.status_color = "The server list has no game server online.", (255, 150, 130); return None
        welcome = next((p.decode("latin1", "replace").replace("\r", " ") for t, p in notes if t == 2), "")
        screen.servers, screen.sel, screen.session = servers, 0, s
        screen.status, screen.status_color = ((welcome + "\n") if welcome else "") + "Choose a server (Up/Down, Enter).", (230, 230, 230)
    except (OSError, ConnectionError) as e:
        import crashguard; crashguard.note("login failed (network)")
        screen.status, screen.status_color = "No contact with the server %s:%s:\n%s" % (listserver[0], listserver[1], str(e)[:70] or type(e).__name__), (255, 150, 130)
    except Exception as e:
        import crashguard; crashguard.note("login failed (error)")
        screen.status, screen.status_color = "Error: %s: %s\n(see crash.log)" % (type(e).__name__, str(e)[:60]), (255, 150, 130)
    finally: screen.busy = False
    return None

def join(screen, win):
    """Join pressed: log in at the chosen game server and tell it the nickname. Returns a Session or None."""
    sv = screen.servers[screen.sel]; s = screen.session; nick = screen.vals["nick"].strip()
    screen.busy = True; screen.status, screen.status_color = "Logging in at %s:%d ..." % (sv["host"], sv["port"]), (230, 230, 230)
    win.present(screen.draw(time.time()).tobytes())
    try:
        s.connect([(sv["host"], sv["port"])]); s.pump(2.5)
        if not s.level_name: s.pump(2.5)
        if not s.level_name:
            try: s.close()
            except Exception: pass
            screen.servers = None
            why = s.disc_message[:70] or "It sent no level. The account may be saved at a place\nthat no longer exists; ask the server admin to move it."
            screen.status, screen.status_color = "The game server did not let you in:\n" + why, (255, 150, 130); return None
        if nick: s.set_nickname(nick)
        save_saved(screen.vals); return s
    except (OSError, ConnectionError) as e:
        import crashguard; crashguard.note("login failed (network)")
        why = getattr(s, "disc_message", "")
        screen.servers = None; screen.status, screen.status_color = ("The game server did not let you in:\n" + why[:70]) if why else "No contact with the server:\n%s" % (str(e)[:70] or type(e).__name__), (255, 150, 130); return None
    except Exception as e:
        import crashguard; crashguard.note("login failed (error)")
        screen.servers = None; screen.status, screen.status_color = "Error: %s: %s\n(see crash.log)" % (type(e).__name__, str(e)[:60]), (255, 150, 130); return None
    finally: screen.busy = False

def launch_build():
    """The Build button: open the level editor in its own window (it works offline)."""
    import subprocess
    try: subprocess.Popen([sys.executable, os.path.join(HERE, "editor.py")], cwd=HERE)
    except OSError: pass

def run(version="222", listserver=("127.0.0.1", 9111), game_host=None, scale=1, win=None):
    own = win is None
    win = win or window.Window("Graal - Log in", W, H, scale)
    screen = Screen(load_saved()); hover = None
    try:
        while True:
            for ev in win.events():
                act = None
                if ev[0] == "quit": return None
                elif ev[0] == "down" or (ev[0] == "repeat" and ev[1] in window.REPEATING): act = screen.key(ev[1])
                elif ev[0] == "text": screen.typed(ev[1])
                elif ev[0] == "mousemove": hover = screen.hit(ev[1], ev[2])
                elif ev[0] == "mousedown" and ev[1] == 1:
                    h = screen.hit(ev[2], ev[3])
                    if h == "build": launch_build()
                    elif h == "start": act = "join" if screen.servers else "start"
                    elif h and h.startswith("row"): screen.sel = int(h[3:])
                    elif h: screen.focus = h
                if act == "quit": return None
                if act == "start": contact(screen, win, version, listserver, game_host)
                elif act == "join" and screen.servers:
                    s = join(screen, win)
                    if s is not None: return s
            win.present(screen.draw(time.time(), hover).tobytes()); time.sleep(0.03)
    finally:
        if own: win.close()
