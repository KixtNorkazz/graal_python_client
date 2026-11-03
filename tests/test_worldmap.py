"""python3 test_worldmap.py : the map (M): level pictures, the other players on the same gmap, no map outside a gmap."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import time
from PIL import Image
import gclient, offline, window, worldmap

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500), account="TestA"); s.send = lambda l: None
    rows = s.gmap_rows(); wm = worldmap.WorldMap()
    check(not wm.open and wm.draw(Image.new("RGBA", (640, 480)), s) is None, "closed: nothing is drawn")
    wm.toggle(s); check(wm.open, "M opens the map")
    s.online = {5: dict(NICKNAME="Alice", ACCOUNTNAME="alice", LEVEL=rows[2][3], X2=300, Y2=700),
                6: dict(NICKNAME="Bob", ACCOUNTNAME="bob", LEVEL=rows[5][9], X2=900, Y2=100),
                7: dict(NICKNAME="Elsewhere", ACCOUNTNAME="far", LEVEL="nowhere.nw", X2=1, Y2=1),
                8: dict(NICKNAME="NPC-Server", ACCOUNTNAME="(npcserver)", LEVEL=rows[0][0]),
                9: dict(NICKNAME="Nowhere yet", ACCOUNTNAME="carol", LEVEL=rows[1][1]),
                10: dict(NICKNAME="Gmap style", ACCOUNTNAME="dave", LEVEL="turtlejunction-.gmap", GMAPLEVELX=4, GMAPLEVELY=1, X2=100, Y2=200),
                11: dict(NICKNAME="Outside", ACCOUNTNAME="erin", LEVEL="turtlejunction-.gmap", GMAPLEVELX=40, GMAPLEVELY=1),
                12: dict(NICKNAME="Other gmap", ACCOUNTNAME="fay", LEVEL="other.gmap", GMAPLEVELX=1, GMAPLEVELY=1)}
    pl = wm.players(s, rows)
    check([p[1] for p in pl] == ["alice", "bob", "dave", "carol"], f"only players on this gmap, no npc server, none outside the map: {[p[1] for p in pl]}")
    check(pl[0][2:6] == (3, 2, 300, 700) and pl[3][4:6] == (512, 512) and pl[2][2:6] == (4, 1, 100, 200) and not any(p[6] for p in pl), "cell from the level name or from GMAPLEVELX / Y, position in the level (the middle if unknown)")
    check(wm.own_cell(s, rows) == (7, 3), "our own cell is where our level is in the gmap")
    check(wm.is_near((7, 3), 8, 4) and not wm.is_near((7, 3), 9, 3) and not wm.is_near(None, 0, 0), "players within one cell (the 3 x 3 cells gs2emu sends moves for) are live, farther ones are last known")
    s.map_positions = {"bob": (s.gmap, 9.5 * 1024 + 0.0, 5.25 * 1024, time.time()), "alice": (s.gmap, 0.0, 0.0, time.time() - 60)}
    pl = {p[1]: p for p in wm.players(s, rows)}
    check(pl["bob"][2:] == (9, 5, 512.0, 256.0, True) and pl["alice"][6] is False, "a fresh answer from the server gives the live position (cell and place in it), an old one is ignored")
    s.map_positions = {}
    made = wm.update(s, 4); check(made == 4 and len(wm.thumbs) == 4, "pictures are made a few per call")
    while wm.update(s, 50): pass
    check(len(wm.thumbs) == sum(len(r) for r in rows), "every level of the gmap gets a picture")
    im = Image.new("RGBA", (640, 480), (0, 0, 0, 255)); wm.mouse(300, 200); wm.draw(im, s)
    check(im.getbbox() is not None and im.getpixel((320, 240)) != (0, 0, 0, 255), "the map is drawn")
    a = wm.thumbs[rows[3][7]]; check(a.size == (64, 64) and len({a.getpixel((x, y)) for x in range(64) for y in range(64)}) > 3, "a level picture has the colours of its tiles")
    wm.key(ord("m"), s); check(not wm.open, "M closes it again"); wm.toggle(s); wm.key(window.K_ESCAPE, s); check(not wm.open, "Esc closes it")
    plain = offline.OfflineSession("turtlejunction-h4.nw", pos=(320, 416), account="TestA"); plain.send = lambda l: None
    wm2 = worldmap.WorldMap(); wm2.toggle(plain); im2 = Image.new("RGBA", (640, 480), (0, 0, 0, 255)); wm2.draw(im2, plain)
    check(im2.getbbox() is not None, "outside a gmap it says there is no map")
    t = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(t, "a", "b", "222", ("127.0.0.1", 1)); t.send = lambda l: None
    from graalproto import gchar, gint_enc
    def prop(pid, val): return gchar(pid) + gchar(len(val)) + val
    t.handle("pkt", 8, gint_enc(7, 2) + prop(0, b"Zed") + prop(34, b"zed") + prop(20, b"lev.nw"))
    t.handle("pkt", 8, gint_enc(7, 2) + gchar(78) + gint_enc(600 * 2 + 0, 2) + gchar(79) + gint_enc(200 * 2, 2) + gchar(43) + gchar(4) + gchar(44) + gchar(5))
    o = t.online[7]; check(o.get("GMAPLEVELX") == 4 and o.get("GMAPLEVELY") == 5 and o.get("X2") == 600 and o.get("Y2") == 200, f"the server's position updates are kept for the map: {o}")
    t.map_positions = {}; sent = []; t.send = lambda l: sent.append(bytes(l))
    check(t.request_map_players() and sent[-1][:1] == gchar(38) and b"servermapplayers" in sent[-1] and not t.request_map_players(), "the map asks the server for the positions, at most every few seconds")
    reply = gint_enc(2, 2) + b'"","MAPPLAYERSbob,worldmap.gmap,94,30.5,carol,worldmap.gmap,3,4"'
    t.handle("pkt", 37, reply)
    check(t.map_positions["bob"][:3] == ("worldmap.gmap", 94 * 16.0, 30.5 * 16) and t.map_positions["carol"][1] == 48.0 and not t.pm and not t.pm_log, "the reply is read, and it is not shown as a private message")
    t.handle("pkt", 37, gint_enc(5, 2) + b'"","hello"'); check(t.pm_log and t.pm_log[-1]["text"] == "hello", "an ordinary private message still is one")
    print("worldmap tests passed")

main()
