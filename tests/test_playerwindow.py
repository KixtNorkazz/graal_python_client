"""python3 test_playerwindow.py : the player list in a window of its own, with real SDL windows and xdotool (skipped without a display, SDL or xdotool)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import shutil, subprocess, time

def main():
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"): print("playerwindow tests skipped (no display or xdotool)"); return
    import gclient, playerlist, window
    from graalproto import gchar, gint_enc
    try: main_win = window.Window("test game window", 320, 240)
    except Exception as e: print("playerwindow tests skipped:", e); return
    def props(*items):
        out = b""
        for pid, val in items: out += gchar(pid) + gchar(len(val)) + val
        return out
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    for i, n in enumerate(("Amy", "Bob", "Cat")): s.handle("pkt", 8, gint_enc(5 + i, 2) + props((0, n.encode()), (34, n.lower().encode()), (20, b"x.nw")))
    pl = playerlist.PlayerList(); pl.toggle(s, main_win); ok = False
    try:
        assert pl.open and pl.win is not None and pl.win is not main_win, "the list has its own window"
        def run(*a): subprocess.run(["xdotool", *a], check=False, capture_output=True)
        def frames(n=12):
            for _ in range(n): pl.pump(s); list(main_win.events()); main_win.present(bytes(320 * 240 * 4)); time.sleep(0.04)
        frames(); found = subprocess.run(["xdotool", "search", "--pid", str(os.getpid())], capture_output=True, text=True).stdout.split()
        geo = {w: subprocess.run(["xdotool", "getwindowgeometry", w], capture_output=True, text=True).stdout for w in found}
        mine = [w for w, g in geo.items() if "%dx%d" % playerlist.WINDOW_SIZE in g]
        assert len(found) == 2 and len(mine) == 1, f"the game window and a second window with the player list exist: {geo}"
        wid = mine[0]; run("windowraise", wid); run("windowfocus", wid); frames()
        row = playerlist.WINDOW_PANEL[1] + 26 + playerlist.ROW_H + 4
        run("mousemove", "--window", wid, "60", str(row)); run("click", "1"); frames()
        assert pl.cursor == 1, f"a click in the list window selects the row under it: {pl.cursor}"
        run("click", "--repeat", "2", "--delay", "80", "1"); frames(); assert pl.compose, "a double click starts a message"
        for ch in "hey": run("keydown", ch); run("keyup", ch); frames(3)
        assert pl.text == "hey", f"typing in the list window goes to the message: {pl.text!r}"
        s.last_pm_sent = 0; run("key", "Return"); frames(); assert sent and not pl.compose, "Enter sends it"
        run("key", "Escape"); frames(); assert not pl.open and pl.win is None, "Esc closes the list window"
        ok = True
    finally:
        pl.close_window(); main_win.close()
    print("playerwindow tests passed" if ok else "playerwindow tests FAILED")
    if not ok: sys.exit(1)

main()
