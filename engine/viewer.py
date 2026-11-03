"""Interactive Graal client window (SDL2 via ctypes).

  GRAAL_PASSWORD=... python3 viewer.py --account TestA [--scale 2] [--version 222|231] [--game-host HOST]

Keys: arrow keys walk (hold), A = grab / lift / throw (hold A and walk backwards = pull), Q = inventory list (choose the active weapon), S = sword (a mounted weapon attacks), D = use the active weapon, F1 = settings (sound on/off, volume of sound effects and of looped sounds), Tab or Enter = chat, F11 = fullscreen on/off, 1-9 = pick weapon n, Enter = open chat / send, Esc = cancel chat or quit, F12 = save screenshot.
Walls (tile types) and NPC shapes block movement. S cuts classic bushes; dropped items are picked up by walking over them.
Walking over a level link enters it; walking over a gmap edge moves to the neighbouring sub-level.
"""
import argparse, getpass, os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
from gclient import Session
import render, window
from inventory import Inventory
from playerlist import PlayerList, K_F7
from worldmap import WorldMap
from appearance import Appearance
from chatline import History

W, H, BAR = 640, 480, 24
KEYDIR = {window.K_LEFT: "L", window.K_RIGHT: "R", window.K_UP: "U", window.K_DOWN: "D"}

def main():
    import weapons, gs2src, particles; weapons.REAL_RANDOM = True; gs2src.REAL_RANDOM[0] = True; particles.REAL[0] = True
    ap = argparse.ArgumentParser()
    ap.add_argument("--account"); ap.add_argument("--offline", help="RP server .nw level or .gmap (no server)"); ap.add_argument("--cell"); ap.add_argument("--pos"); ap.add_argument("--weapon", action="append", default=[], help="weapon file (container or bare script) to add, for testing"); ap.add_argument("--state", help="offline: JSON file with the persistent state (variables, inventory, weapons, opened chests); loaded at start, saved every 30 s and at exit"); ap.add_argument("--version", default="222", choices=("222", "231"))
    import config; ap.add_argument("--listserver", default=config.CFG["listserver"], help="list server host:port (default: paths.json key listserver)"); ap.add_argument("--game-host")
    ap.add_argument("--scale", type=float, default=1, help="window size factor (1 = 640x480; F11 toggles fullscreen)"); ap.add_argument("--shots", default=".")
    a = ap.parse_args()
    if a.offline:
        from offline import OfflineSession
        pair = lambda v: tuple(int(x) for x in v.split(",")) if v else None
        s = OfflineSession(a.offline, pair(a.cell), pair(a.pos)); a.account = "offline"
        if a.state: s.load_state(a.state)
    else:
        host, port = a.listserver.rsplit(":", 1)
        if not a.account:
            import login_gui
            s = login_gui.run(a.version, (host, int(port)), a.game_host)
            if s is None: return
            a.account = s.account.decode("latin1"); s.pump(1.0); s.ensure_neighbours(); s.pump(0.5)
        else:
            pw = os.environ.get("GRAAL_PASSWORD") or getpass.getpass("Password: ")
            s = Session(a.account, pw, a.version, (host, int(port)), a.game_host)
            s.connect(); s.pump(1.5); s.ensure_neighbours(); s.pump(0.5)
    import re
    for wf in a.weapon:
        t = open(wf, encoding="latin1").read(); m = re.search(r"^SCRIPT\n(.*?)^SCRIPTEND", t, re.S | re.M)
        s.runner.add("-" + os.path.basename(wf), "", m.group(1) if m else t)
    import audio, settings; s.audio = audio.Audio(device=True)
    stw = settings.SettingsWindow(); settings.apply(s, stw.values)
    win = window.Window(f"Graal python client - {a.account}", W, H, a.scale)
    font = ImageFont.load_default()

    inv = Inventory(); hist = History(); pl = PlayerList(); wm = WorldMap(); ap_ = Appearance()
    held, walking, walk_start, next_tick, typing, text, shot_n = [], False, 0.0, 0.0, False, "", 0
    first_step, last_frame, fps = True, time.monotonic(), 0.0
    running = True
    last_save = time.time()
    while running:
        now = time.monotonic()
        for ev in win.events():
            if ev[0] == "quit": running = False
            elif ev[0] == "wheel" and ap_.open: ap_.wheel(ev[1])
            elif ev[0] == "wheel":
                if not s.gui.wheel(s.input.sx, s.input.sy, ev[1]): s.input.wheel(ev[1])
            elif ev[0] == "mousemove" and wm.open: wm.mouse(ev[1], ev[2])
            elif ev[0] == "mousemove":
                if not s.gui.mouse("move", 0, ev[1], ev[2]): s.input.mouse_move(ev[1], ev[2])
            elif ev[0] in ("mousedown", "mouseup"):
                if s.gui.mouse("down" if ev[0] == "mousedown" else "up", ev[1], ev[2], ev[3]): continue
                if stw.open:
                    if ev[0] == "mousedown": stw.click(ev[2], ev[3], s)
                    continue
                if ap_.open:
                    if ev[0] == "mousedown": ap_.click(ev[2], ev[3], s)
                    continue
                if wm.open: continue
                if ev[0] == "mousedown" and inv.open and inv.click(ev[2], ev[3], s): continue
                if not typing and ev[3] < H - BAR: s.input.mouse_button(ev[1], ev[0] == "mousedown", ev[2], ev[3])
                elif ev[0] == "mouseup": s.input.mouse_button(ev[1], False, ev[2], ev[3])
            elif ev[0] == "down" and s.gui.capturing() and ev[1] != window.K_F12: s.gui.key(ev[1], True)
            elif ev[0] == "down" and getattr(s, "msgbox", None) is not None and not typing and not s.msgbox.expired() and s.msgbox.key(ev[1]): held.clear()
            elif ev[0] == "down" and stw.open and not typing and ev[1] != window.K_F12: stw.key(ev[1], s); held.clear()
            elif ev[0] == "down" and ap_.open and not typing and ev[1] != window.K_F12: ap_.key(ev[1], s); held.clear()
            elif ev[0] == "down" and wm.open and not typing and ev[1] != window.K_F12: wm.key(ev[1], s); held.clear()
            elif ev[0] == "down" and inv.open and not typing and ev[1] != window.K_F12: inv.key(ev[1], s)
            elif ev[0] == "down":
                k = ev[1]
                if not typing and k != window.K_F12: s.input.key(k, True)
                if typing:
                    if k == window.K_RETURN:
                        if text.strip(): hist.push(text); s.say(text); s.runner.broadcast("playerchats", chat=text); s.npcrt.broadcast("playerchats", text)
                        typing, text = False, ""
                    elif k in (window.K_ESCAPE, window.K_TAB): typing, text = False, ""
                    elif k == window.K_BACKSPACE: text = text[:-1]
                    elif k == window.K_UP: text = hist.up(text)
                    elif k == window.K_DOWN: text = hist.down(text)
                elif k in (window.K_RETURN, window.K_TAB): typing = True; held.clear(); hist.reset()
                elif k == window.K_ESCAPE: running = False
                elif k == window.K_F12:
                    img = render_frame(s, now, walking, walk_start, typing, text, font, fps, inv, pl, wm, ap_, stw)
                    path = os.path.join(a.shots, f"shot_{shot_n:03d}.png"); img.convert("RGB").save(path); shot_n += 1; print("saved", path)
                elif k == ord("q"): inv.toggle(s); held.clear(); walking = False
                elif k == ord("d") and not s.frozen(): print("weapon:", inv.fire(s)); walking = False
                elif ord("1") <= k <= ord("9") and not s.frozen(): inv.choose(s, k - ord("1"))
                elif k == ord("h") and s.me.get("HORSEIMAGE"): s.dismount()
                elif k == ord("a") and not s.attacking() and not s.frozen(): s.grab()
                elif k == settings.K_F1: stw.toggle(s); held.clear(); walking = False
                elif k == window.K_F11: win.toggle_fullscreen()
                elif k == K_F7: pl.toggle(s, win)
                elif k == ord("m"): wm.toggle(s); held.clear(); walking = False
                elif k == ord("f"): ap_.toggle(s); held.clear(); walking = False
                elif k == ord("s") and not s.attacking() and not s.frozen():
                    walking = False; s.attack()
                elif k in KEYDIR and KEYDIR[k] not in held: held.append(KEYDIR[k])
            elif ev[0] == "up":
                if ev[1] != window.K_F12: s.input.key(ev[1], False)
                if ev[1] in KEYDIR and KEYDIR[ev[1]] in held: held.remove(KEYDIR[ev[1]])
            elif ev[0] == "repeat" and typing and ev[1] == window.K_BACKSPACE: text = text[:-1]
            elif ev[0] == "repeat" and s.gui.capturing() and ev[1] in window.REPEATING: s.gui.key(ev[1], True)
            elif ev[0] == "text" and s.gui.capturing(): s.gui.typed(ev[1])
            elif ev[0] == "text" and ap_.open: ap_.typed(ev[1])
            elif ev[0] == "text" and typing: text = (text + ev[1])[:100]
        try:
            s.poll()
            if held and getattr(s, "msgbox", None) is not None and not s.msgbox.multi: s.msgbox = None
            if a.offline and a.state and time.time() - last_save > 30: s.save_state(a.state); last_save = time.time()
            if next_tick == 0.0: next_tick = now
            catch_up = 0
            while now >= next_tick and catch_up < 4:
                next_tick += 0.05; catch_up += 1
                if s.me.get("GANI") == s.resolve_ani("sword") and not s.attacking():
                    s.stop()
                if s.attacking() or s.frozen() or not s.defmovement or s.walking_to(): pass
                elif held and s.level_name:
                    if not walking: walking, walk_start, first_step = True, now, True
                    link = None
                    dirs_ = walk_dirs(held)
                    for i_, d_ in enumerate(dirs_):
                        link = s.step(d_, first_step and i_ == len(dirs_) - 1)
                        if link: break
                    first_step = False
                    if link: walking = False; held.clear(); break
                elif walking: walking = False; s.stop()
            if now - next_tick > 0.5: next_tick = now
            if not walking and s.items: s.pickup_items()
            if s.me.get("MESSAGE") and time.time() - getattr(s, "say_time", 0) > 6: s.clear_chat()
        except (ConnectionError, OSError) as e:
            print("disconnected:", e); break
        pl.pump(s)
        img = render_frame(s, now, walking, walk_start, typing, text, font, fps, inv, pl, wm, ap_, stw)
        win.present(img.tobytes())
        if s.gmap and s.level_name and time.monotonic() - now < 0.02:
            try: render.prebuild_one(s.levels, s.npcs, s.weapons, s.gmap, s.level_name)
            except Exception: pass
        dt = time.monotonic() - last_frame; last_frame = time.monotonic(); fps = 0.9 * fps + 0.1 / dt if dt > 0 else fps
        win.title(f"Graal python client - {a.account} - {s.level_name or 'loading'} {s.pos}")
        time.sleep(max(0.0, 0.025 - (time.monotonic() - now)))
    if a.offline and a.state: s.save_state(a.state)
    try: s.stop(); s.pump(0.2); s.close()
    except Exception: pass
    pl.close_window()
    win.close()

def pending_label(s):
    f = getattr(s, "files", None); n = len(f.queue) + len(f.out) if f else 0
    import assets
    miss = "   pics1.png missing (see README): no tiles" if "pics1.png" not in assets.index() else ""
    return (f"   downloading {n} files" if n else "") + miss

def walk_dirs(held):
    """The directions to step this tick from the held arrows (oldest press first): the latest horizontal and the latest vertical one; one arrow = one direction."""
    h = [d for d in held if d in "LR"][-1:]; v = [d for d in held if d in "UD"][-1:]
    return sorted(h + v, key=held.index)

def snap_texts(s): return list(s.texts.values())
def snap_sign(s): return s.sign[0] if time.time() < s.sign[1] else ""

def render_frame(s, now, walking, walk_start, typing, text, font, fps, inv, pl, wm, ap_, stw=None):
    out = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    snap = s.snapshot()
    lv = s.levels.get(s.level_name) if s.level_name else None
    if lv and lv.board:
        try:
            base = (s.me.get("GANI") or "idle").split(",")[0]
            t = (now - walk_start) if (walking and base in (s.resolve_ani("walk"), "swim")) else (time.time() - s.gani_start if base not in ("idle", "walk") else 0.0)
            out.paste(render.render_scene(snap, size=(W, H - BAR), t=t), (0, 0))
        except Exception:
            traceback.print_exc()
    me = s.me
    render.draw_hud(out, me, snap.get("hud_hidden", False))
    pd = ImageDraw.Draw(out, "RGBA")
    for pid_, pts in snap.get("polys", {}).items():
        if len(pts) >= 6: pd.polygon([(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)], fill=(20, 20, 40, 150), outline=(255, 255, 255, 220))
    for t_ in snap_texts(s): render.draw_chat(out, t_["text"], t_["x"] + 40, t_["y"] + 14)
    mb = getattr(s, "msgbox", None)
    if mb is not None:
        if mb.expired(): s.msgbox = None
        else: mb.draw(out)
    s.gui.render(out)
    if not inv.open: render.draw_chat(out, inv.status(s), 320, 40)
    inv.draw(out, s); pl.draw(out, s); wm.draw(out, s); ap_.draw(out, s)
    if stw is not None: stw.draw(out, s)
    d = ImageDraw.Draw(out); d.rectangle((0, H - BAR, W, H), fill=(255, 255, 255, 255))
    label = f"> {text}_" if typing else f"{s.level_name or 'loading...'}  ({s.pos[0] // 16},{s.pos[1] // 16})   Enter = chat   {fps:3.0f} fps{pending_label(s)}"
    d.text((6, H - BAR + 6), label, font=font, fill=(0, 0, 0, 255))
    return out

if __name__ == "__main__":
    import crashguard; crashguard.run(main)
