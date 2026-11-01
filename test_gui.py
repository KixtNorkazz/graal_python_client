"""python3 test_gui.py : GS2 GUI (new GuiWindowCtrl ..., waitfor, events, mouse/keyboard) on the real RP server GuiInputDialog weapon."""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline
from PIL import Image

import config
BASE = config.dirs("weapon_dirs")[0] + os.sep

def check(c, m):
    if not c: raise AssertionError(m)

def script(name):
    t = open(BASE + name, encoding="latin1").read(); m = re.search(r"^SCRIPT\n(.*?)^SCRIPTEND", t, re.S | re.M); return m.group(1) if m else t

def pump(s, secs=0.3):
    t0 = time.time()
    while time.time() - t0 < secs: s.runner.tick(); s.npcrt.tick(); time.sleep(0.02)

def main():
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500))
    s.runner.add("-GuiInputDialog", "", script("weapon%045%043GuiInputDialog.txt")); w = s.runner.weapons["-GuiInputDialog"]
    check(w.gs2, f"GuiInputDialog parses {s.log}")
    s.runner.broadcast("playerchats", chat="/showinputdialog"); pump(s, 0.1)
    g = s.gui
    for n in ("inputdialog", "inputdialog_field", "inputdialog_button", "inputdialog_buttoncancel", "inputdialog_label", "inputdialog_frame"): check(n in g.objs, f"control {n} created: {sorted(g.objs)}")
    win = g.objs["inputdialog"]
    check(win.get("extent") == [240.0, 123.0] and win.get("position") == [200.0, 178.5] and win.get("text") == "Input Dialog", f"window props {win.a}")
    check(g.objs["inputdialog_field"].get("text") == "" and g.objs["inputdialog_label"].parent is g.objs["inputdialog_frame"], "nested creation / parameters")
    check(g.waiters and g.waiters[0].target == "inputdialog_button", "show() is suspended in waitfor")
    img = Image.new("RGBA", (640, 456), (40, 90, 40, 255)); g.render(img)
    check(img.getpixel((210, 185)) == (10, 36, 106, 255), f"title bar drawn {img.getpixel((210, 185))}")
    x0, y0, x1, y1 = g.objs["inputdialog_field"].box(); cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    check(g.mouse("down", 1, cx, cy) and g.focus is g.objs["inputdialog_field"], "click focuses the edit field"); g.mouse("up", 1, cx, cy)
    for ch in "hello": g.typed(ch)
    g.key(8, True); g.typed("o"); check(g.objs["inputdialog_field"].get("text") == "hello", "typing + backspace")
    bx0, by0, bx1, by1 = g.objs["inputdialog_button"].box(); bx, by = (bx0 + bx1) / 2, (by0 + by1) / 2
    g.mouse("down", 1, bx, by); check(g.pressed is g.objs["inputdialog_button"], "button pressed"); g.mouse("up", 1, bx, by); pump(s, 0.2)
    check(any(l == "echo: Input: hello" for l in s.log), f"waitfor resumed with the field text: {[l for l in s.log if 'echo' in l or 'gs2' in l]}")
    check("inputdialog" not in g.objs and not g.roots, "dialog destroyed after OK")
    s.runner.broadcast("playerchats", chat="/showinputdialog"); pump(s, 0.1)
    g.objs["inputdialog_field"].set("text", "x"); cx0, cy0, cx1, cy1 = g.objs["inputdialog_buttoncancel"].box(); mx, my = (cx0 + cx1) / 2, (cy0 + cy1) / 2
    g.mouse("down", 1, mx, my); g.mouse("up", 1, mx, my); pump(s, 0.2)
    check(s.log[-1] == "echo: Input: ", f"cancel returns the cleared field {s.log[-2:]}")
    s.runner.broadcast("playerchats", chat="/showinputdialog"); pump(s, 0.1); check("inputdialog" in g.objs, "dialog open again")
    wx0, wy0, _, _ = g.objs["inputdialog"].box(); g.mouse("down", 1, wx0 + 40, wy0 + 5); g.mouse("move", 0, wx0 + 90, wy0 + 55); g.mouse("up", 1, wx0 + 90, wy0 + 55)
    check(g.objs["inputdialog"].get("x") == 250.0, f"window dragged {g.objs['inputdialog'].a['position']}")
    s2 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500)); g2 = s2.gui
    long = " ".join(["line %d of the console output" % k for k in range(60)])
    src = """//#CLIENTSIDE
function onCreated() {
  new GuiWindowCtrl("W") {
    position = {20, 20}; extent = {300, 200}; text = "Scroll test"; canMove = true;
    new GuiScrollCtrl("Sc") {
      position = {6, 24}; extent = {280, 150};
      new GuiMLTextCtrl("Tx") { position = {0, 0}; extent = {260, 20}; text = "%s"; }
    }
  }
}
""" % long
    s2.runner.add("-ScrollTest", "", src); s2.runner.run_event(s2.runner.weapons["-ScrollTest"], "created")
    img = Image.new("RGBA", (640, 456), (40, 90, 40, 255)); g2.render(img)
    sc = g2.objs["sc"]; my = g2.max_scroll(sc)[0]
    check(my > 100 and g2.bar_visible(sc), f"content taller than the viewport after the first draw: max scroll {my}")
    check(g2.wheel(100, 100, -3) and abs(sc.scroll_pos[1] - 72) < 1e-6, f"wheel scrolls by 24 px per notch {sc.scroll_pos}")
    g2.wheel(100, 100, 50); check(sc.scroll_pos[1] == 0.0, "scroll clamps at the top")
    tx = g2.objs["tx"]; check(tx.abs_pos()[1] == tx.a["position"][1] + 20 + 24 - sc.scroll_pos[1], "child positions follow the scroll")
    g2.wheel(100, 100, -500); check(abs(sc.scroll_pos[1] - my) < 1e-6, "scroll clamps at the bottom")
    g2.render(img); sc.call("scrolltotop", []); check(sc.scroll_pos[1] == 0.0, "scrollToTop()")
    sx0, sy0, sx1, sy1 = sc.box(); th = g2.thumb(sc); gx = sx1 - 6; gy = sy0 + th[0] + th[1] / 2
    g2.mouse("down", 1, gx, gy); check(g2.drag and g2.drag[0] == "sb", "thumb grabbed"); g2.mouse("move", 0, gx, gy + 40); g2.mouse("up", 1, gx, gy + 40)
    check(sc.scroll_pos[1] > 20, f"dragging the thumb scrolls {sc.scroll_pos}")
    sc.scroll_pos[1] = 0.0; g2.mouse("down", 1, gx, sy1 - 5); g2.mouse("up", 1, gx, sy1 - 5); check(sc.scroll_pos[1] > 100, "click in the track pages down")
    check(g2.mouse("down", 1, 400, 300) is False, "clicks outside every control go to the game")
    print("gui tests passed")

if __name__ == "__main__": main()
