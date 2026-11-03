"""python3 test_playerlist.py : player list (F7) and private messages: online list from OTHERPLPROPS, leaving, sending, receiving, drawing."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import time
from PIL import Image
import gclient, playerlist, window
from graalproto import gchar, gint_enc

def check(c, m):
    if not c: raise AssertionError(m)

def props(*items):
    out = b""
    for pid, val in items: out += gchar(pid) + gchar(len(val)) + val
    return out

def main():
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    s.handle("pkt", 8, gint_enc(7, 2) + props((0, b"Zed (Guild)"), (34, b"zed"), (20, b"lev.nw")))
    s.handle("pkt", 8, gint_enc(5, 2) + props((0, b"Amy"), (34, b"amy"), (20, b"x.nw")))
    s.handle("pkt", 8, gint_enc(2, 2) + props((0, b"NPC-Server"), (34, b"(npcserver)")))
    names = [p["account"] for p in s.online_players()]
    check(names == ["amy", "zed"], f"sorted by nickname, the npc server is left out: {names}")
    s.handle("pkt", 8, gint_enc(7, 2) + bytes([gchar(50)[0], gchar(0)[0]]))
    check(len(s.online_players()) == 2, "leaving a level does not remove a player from the list")
    s.handle("pkt", 8, gint_enc(7, 2) + gchar(51))
    check([p["account"] for p in s.online_players()] == ["amy"], "DISCONNECT removes the player")
    ok, why = s.send_pm([5], 'Hi "you"')
    check(ok and sent[-1][:1] == gchar(28) and sent[-1][1:3] == gint_enc(1, 2) and sent[-1][3:5] == gint_enc(5, 2) and b'""you""' in sent[-1], f"PM packet: {sent[-1]!r}")
    s.handle("pkt", 8, gint_enc(11, 2) + bytes([gchar(50)[0], gchar(1)[0]]))
    check(11 not in [p["id"] for p in s.online_players()], "a level-only packet for an unknown id does not add a nameless player")
    ok, why = s.send_pm([5], "again"); check(not ok and "wait" in why, "one message every 4 seconds")
    check(s.send_pm([5], "script", limit=False)[0], "scripts (sendpm) are not held back by the 4 second limit")
    s.handle("pkt", 37, gint_enc(5, 2) + b'"","Private message:","hello there"')
    check(s.pm_log[-1] == dict(s.pm_log[-1], dir="in", who="Amy", text="Private message: hello there".split(": ", 1)[1]) and s.pm_log[-2]["dir"] == "out", f"received PM logged: {s.pm_log}")
    pl = playerlist.PlayerList(); im = Image.new("RGBA", (640, 480))
    pl.draw(im, s); check(im.getbbox() is not None, "a received PM shows a notice while the list is closed")
    pl.toggle(s); check(pl.open, "F7 opens the list")
    pl.key(window.K_RETURN, s); pl.typed("h"); pl.typed("i"); check(pl.compose and pl.text == "hi", "Enter starts a message")
    s.last_pm_sent = 0; n = len(sent); pl.key(window.K_RETURN, s); check(not pl.compose and len(sent) == n + 1, "Enter sends it")
    pl.compose = False; px, py, _ = pl.panel; ry = py + 26 + 3
    s.handle("pkt", 8, gint_enc(9, 2) + props((0, b"Bob"), (34, b"bob"), (20, b"y.nw"))); pl.cursor = 0
    check(pl.click(px + 20, ry + playerlist.ROW_H, s, now=100.0) and pl.cursor == 1 and not pl.compose, "a click selects the row")
    pl.click(px + 20, ry + playerlist.ROW_H, s, now=100.2); check(pl.compose and pl.cursor == 1, "a double click starts a message to that player")
    pl.compose = False; pl.click(px + 20, ry, s, now=101.0); pl.click(px + 20, ry + playerlist.ROW_H, s, now=101.1); check(not pl.compose, "two clicks on different rows are not a double click")
    check(not pl.click(px + 500, ry, s, now=102.0), "a click outside the panel is not used")
    pl.draw(im, s); pl.key(playerlist.K_F7, s); check(not pl.open, "F7 closes the list")
    print("playerlist tests passed")

main()
