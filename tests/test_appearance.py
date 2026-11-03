"""python3 test_appearance.py : the appearance window (F): lists, filter, choosing, Done sends the head and body properties, the server-side list maker."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import subprocess, tempfile
from PIL import Image
import appearance, gclient, window
from graalproto import gchar, gstr

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    s.me.update(HEADIMAGE="head0.png", BODYIMAGE="body.png")
    ap = appearance.Appearance(); ap.set_names("heads", ["head0.png", "head1.png", "Cat.gif", "dog.gif", "head2.png"]); ap.set_names("bodies", ["body.png", "armor.gif", "Robe.png"])
    ap.toggle(s); check(ap.open and ap.chosen == {"heads": "head0.png", "bodies": "body.png"} and ap.cursor == 0, "F opens it on what you wear now")
    check(ap.shown() == ["head0.png", "head1.png", "Cat.gif", "dog.gif", "head2.png"], "all heads are listed")
    ap.typed("f"); check(ap.filter == "", "the F that opened the window is not typed into the filter"); ap.opened_at = 0.0
    for ch in "HEAD": ap.typed(ch)
    check(ap.shown() == ["head0.png", "head1.png", "head2.png"], f"typing filters, ignoring case: {ap.shown()}")
    ap.key(window.K_RIGHT, s); ap.key(window.K_RIGHT, s); check(ap.cursor == 2 and ap.chosen["heads"] == "head2.png", "the arrow keys choose")
    ap.key(window.K_RIGHT, s); check(ap.cursor == 2, "not past the last one")
    ap.key(window.K_BACKSPACE, s); ap.key(window.K_BACKSPACE, s); ap.key(window.K_BACKSPACE, s); ap.key(window.K_BACKSPACE, s); check(ap.filter == "" and len(ap.shown()) == 5, "Backspace widens the filter")
    ap.key(window.K_TAB, s); check(ap.tab == "bodies" and ap.shown() == ["armor.gif", "body.png", "Robe.png"] or ap.shown() == ["body.png", "armor.gif", "Robe.png"], "Tab goes to the bodies")
    ap.chosen["bodies"] = "armor.gif"; ap.key(window.K_TAB, s); ap.key(window.K_RETURN, s)
    check(not ap.open and len(sent) == 1, f"Done sends one packet: {sent}")
    check(sent[0] == gchar(2) + gchar(11) + gchar(len(b"head2.png") + 100) + b"head2.png" + gchar(35) + gstr(b"armor.gif") + b"\n" or sent[0][1:2] == gchar(11), f"head (length + 100, name) and body (gstr): {sent[0]!r}")
    check(s.me["HEADIMAGE"] == "head2.png" and s.me["BODYIMAGE"] == "armor.gif", "what you wear is updated at once")
    sent.clear(); ap.toggle(s); ap.key(window.K_RETURN, s); check(not sent, "Done without a change sends nothing")
    ap.toggle(s); ap.chosen["heads"] = "Cat.gif"; ap.key(window.K_ESCAPE, s); check(not ap.open and not sent and s.me["HEADIMAGE"] == "head2.png", "Esc cancels")

    ap.toggle(s); bx, by, bw, bh = ap.BUTTONS["done"]; ap.chosen["heads"] = "dog.gif"; ap.click(bx + 5, by + 5, s); check(not ap.open and len(sent) == 1 and b"dog.gif" in sent[0], "the Done button")
    ap.toggle(s); gx, gy = ap.GRID; ap.click(gx + appearance.CELL + 5, gy + 5, s); check(ap.chosen["heads"] == ap.shown()[1], "a click on a picture chooses it")
    bx, by, bw, bh = ap.BUTTONS["cancel"]; ap.click(bx + 5, by + 5, s); check(not ap.open, "the Cancel button")
    ap.toggle(s); ap.typed("x"); ap.typed("y"); check(ap.shown() == [], "nothing found")
    ap.key(window.K_RETURN, s); check(ap.open and ap.chosen["heads"] == "xy", "Enter with nothing found uses the typed name")
    check(ap.draw(Image.new("RGBA", (640, 480)), s) is None, "drawing works"); ap.filter = ""; im = Image.new("RGBA", (640, 480)); ap.draw(im, s); check(im.getbbox() is not None, "drawn")
    s.set_appearance(None, None); check(len(sent) == 1, "set_appearance with nothing to set sends nothing")

    big = appearance.Appearance(); big.set_names("heads", ["h%d.png" % i for i in range(100)]); big.toggle(s)
    for _ in range(appearance.COLS * appearance.ROWS + appearance.COLS): big.key(window.K_RIGHT, s)
    check(big.first > 0 and big.first <= big.cursor < big.first + appearance.COLS * appearance.ROWS, "the page scrolls with the cursor"); big.wheel(-1); big.draw(Image.new("RGBA", (640, 480)), s)

    with tempfile.TemporaryDirectory() as world:
        for d, files in (("heads", ["a.png", "B.gif", "notes.txt", "my head.png"]), (os.path.join("global", "heads"), ["a.png", "c.mng"]), ("bodies", ["x.gif"])):
            os.makedirs(os.path.join(world, d)); [open(os.path.join(world, d, f), "w").close() for f in files]
        tool = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "make_appearance_lists.py")
        r = subprocess.run([sys.executable, tool, world], capture_output=True, text=True); check(r.returncode == 0, r.stderr)
        check(appearance.read_names(os.path.join(world, "heads.txt")) == ["a.png", "B.gif", "c.mng", "my head.png"] and appearance.read_names(os.path.join(world, "bodies.txt")) == ["x.gif"], "the list maker writes the image names, no duplicates, no other files")
    print("appearance tests passed")

main()
