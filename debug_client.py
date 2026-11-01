"""Diagnosis for the client, Linux and Windows:  python debug_client.py   (Windows: debug.bat)

Checks one thing at a time and says which one fails: Python / Pillow / SDL2 / files / list server / game server / the login window (it shows every key and text event it
receives, so you can see whether typing arrives) / optionally a real login. Everything is also written to debug.log; send that file when asking for help.

  python debug_client.py [--listserver HOST:PORT] [--account NAME --password PW] [--no-gui] [--seconds 25]"""
import argparse, os, platform, socket, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
LOG = open(os.path.join(HERE, "debug.log"), "w", encoding="utf-8")
FAILS = []

def out(*a):
    s = " ".join(str(x) for x in a); print(s); LOG.write(s + "\n"); LOG.flush()

def step(name, fn):
    out("\n== " + name)
    try: r = fn(); out("   OK" + (": " + str(r) if r is not None else "")); return True
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt): raise
        FAILS.append(name); out("   FAILED:", type(e).__name__, e); out(traceback.format_exc()); return False

def system():
    out("   python", sys.version.replace("\n", " ")); out("   bitness", platform.architecture()[0], "| platform", platform.platform(), "| machine", platform.machine())
    out("   folder", HERE, "| cwd", os.getcwd()); out("   argv", sys.argv)
    if sys.version_info < (3, 9): raise RuntimeError("Python 3.9 or newer is needed")

def pillow():
    import PIL; from PIL import Image, ImageDraw, ImageFont, features
    f = ImageFont.load_default(); im = Image.new("RGBA", (40, 20)); ImageDraw.Draw(im).text((0, 0), "Ab", font=f, fill=(255, 255, 255, 255))
    return "Pillow %s, freetype=%s, default font %s" % (PIL.__version__, features.check("freetype2"), type(f).__name__)

def sdl():
    import window, ctypes
    L = window.load_sdl()
    class V(ctypes.Structure): _fields_ = [("major", ctypes.c_uint8), ("minor", ctypes.c_uint8), ("patch", ctypes.c_uint8)]
    v = V(); L.SDL_GetVersion(ctypes.byref(v)); out("   SDL2 version %d.%d.%d" % (v.major, v.minor, v.patch))
    L.SDL_GetCurrentVideoDriver.restype = ctypes.c_char_p; L.SDL_GetNumVideoDrivers.restype = ctypes.c_int; L.SDL_GetVideoDriver.restype = ctypes.c_char_p
    if L.SDL_Init(0x20) != 0: L.SDL_GetError.restype = ctypes.c_char_p; raise RuntimeError("SDL_Init: " + L.SDL_GetError().decode())
    out("   video drivers:", [L.SDL_GetVideoDriver(i).decode() for i in range(L.SDL_GetNumVideoDrivers())], "current:", (L.SDL_GetCurrentVideoDriver() or b"?").decode())
    L.SDL_Quit()

def files():
    import config, assets
    for f in ("logos-1.jpg", "builtin/pics1.png", "builtin/sprites.png", "paths.json"):
        out("   %-22s %s" % (f, "found" if os.path.exists(os.path.join(HERE, f)) else "MISSING"))
    out("   listserver (paths.json / default):", config.CFG["listserver"]); out("   cache_dir:", config.CFG["cache_dir"])
    os.makedirs(config.CFG["cache_dir"], exist_ok=True); t = os.path.join(config.CFG["cache_dir"], ".w"); open(t, "w").write("x"); os.remove(t)
    out("   asset folders that exist:", [d for d in assets.ROOTS if os.path.isdir(d)]); out("   files known:", len(assets.index()))

def tcp(host, port):
    t = time.time(); s = socket.create_connection((host, port), timeout=6); s.close(); return "connected in %.0f ms" % ((time.time() - t) * 1000)

def network(host, port):
    out("   address:", sorted({a[4][0] for a in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)}))
    ok = []
    for p in dict.fromkeys([port, 9111, 14900, 14902]):
        try: out("   TCP %s:%d  %s" % (host, p, tcp(host, p))); ok.append(p)
        except OSError as e: out("   TCP %s:%d  closed / blocked (%s)" % (host, p, e))
    if port not in ok: raise RuntimeError("cannot connect to %s:%d (wrong port, server down, or a firewall)" % (host, port))

def login(host, port, account, password):
    from minclient import list_servers
    servers, notes = list_servers(host, port, account.encode(), password.encode(), False)
    out("   server list:", servers); out("   messages:", [(t, p[:80]) for t, p in notes])
    if not servers: raise RuntimeError("the list server answered but lists no game server")
    out("   game server:", tcp(*servers[0]))
    from gclient import Session
    s = Session(account, password, "222", (host, port)); s.connect(servers); s.pump(4.0)
    out("   level after login:", s.level_name, "| frames", s.frames, "| files fetched", len(s.files.received), "| missing", s.files.missing[:5])
    if not s.level_name: raise RuntimeError("logged in at the game server but no level arrived (wrong password, or the account is still online - wait and retry)")
    s.stop(); s.pump(0.3); s.close()

def gui(seconds):
    import window, login_gui
    win = window.Window("Graal debug - type something, Esc closes", login_gui.W, login_gui.H); scr = login_gui.Screen({})
    out("   window open. Click a field and type; every event is listed. Esc or close the window to continue (%ds max)." % seconds)
    end = time.time() + seconds; n = {"down": 0, "text": 0, "mouse": 0}; shown = 0
    while time.time() < end:
        for ev in win.events():
            if ev[0] == "quit": end = 0
            elif ev[0] == "down": n["down"] += 1; act = scr.key(ev[1]); (shown < 40) and out("   key down", hex(ev[1])); shown += 1; end = 0 if act == "quit" else end
            elif ev[0] == "text": n["text"] += 1; scr.typed(ev[1]); out("   text", repr(ev[1]))
            elif ev[0] in ("mousedown",): n["mouse"] += 1; h = scr.hit(ev[2], ev[3]); out("   click at (%d,%d) -> %s" % (ev[2], ev[3], h)); h in ("nick", "account", "password") and setattr(scr, "focus", h)
        win.present(scr.draw(time.time()).tobytes()); time.sleep(0.03)
    win.close(); out("   events:", n, "| typed values:", {k: ("*" * len(v) if k == "password" else v) for k, v in scr.vals.items()})
    if not n["text"] and not n["down"]: raise RuntimeError("the window got no keyboard events (did it have focus?)")

def main():
    ap = argparse.ArgumentParser(); import config
    ap.add_argument("--listserver", default=config.CFG["listserver"]); ap.add_argument("--account"); ap.add_argument("--password"); ap.add_argument("--no-gui", action="store_true"); ap.add_argument("--seconds", type=int, default=25)
    a = ap.parse_args(); host, port = a.listserver.rsplit(":", 1); port = int(port)
    out("Graal client diagnosis", time.strftime("%Y-%m-%d %H:%M:%S"), "| target list server", a.listserver)
    step("1. System", system); step("2. Pillow (images/text)", pillow); step("3. SDL2 (window library)", sdl); step("4. Files and folders", files)
    step("5. Network to the list server %s" % a.listserver, lambda: network(host, port))
    if a.account and a.password: step("6. Real login as %s" % a.account, lambda: login(host, port, a.account, a.password))
    else: out("\n== 6. Real login skipped (add --account NAME --password PW)")
    if not a.no_gui: step("7. Login window and keyboard", lambda: gui(a.seconds))
    out("\n" + ("ALL CHECKS PASSED" if not FAILS else "FAILED: " + "; ".join(FAILS)))
    out("Log saved in", os.path.join(HERE, "debug.log"))

if __name__ == "__main__":
    try: main()
    except BaseException: out(traceback.format_exc())
    if sys.platform == "win32" or os.environ.get("GRAAL_PAUSE"):
        try: input("\nPress Enter to close...")
        except EOFError: pass
