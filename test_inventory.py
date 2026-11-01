"""Inventory list: choose the active weapon, S fires it, D switches it on / off."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import window
from inventory import Inventory
from PIL import Image

class W:
    def __init__(self, name): self.name, self.image = name, ""

class R:
    def __init__(self, names): self.ws = [W(n) for n in names]; self.fired = []
    def firable(self): return self.ws
    def fire(self, i): self.fired.append(self.ws[i].name); return self.ws[i].name

class S:
    def __init__(self, names): self.runner = R(names); self.me = {"GRALATS": 12, "BOMBS": 3, "GLOVEPOWER": 1}

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    s = S(["Hat", "Dragon", "Staff"]); inv = Inventory()
    check(inv.fire(s) is None, "nothing active at the start: D does nothing")
    inv.toggle(s); check(inv.open, "Q opens"); inv.key(window.K_DOWN, s); inv.key(window.K_DOWN, s); check(inv.cursor == 2, "down, down")
    inv.key(window.K_DOWN, s); check(inv.cursor == 0, "wraps around"); inv.key(window.K_UP, s); check(inv.cursor == 2, "up wraps back")
    inv.key(window.K_RETURN, s); check(inv.active == "Staff" and not inv.open, "Enter chooses and closes")
    check(inv.fire(s) == "Staff" and inv.fire(s) == "Staff" and s.runner.fired == ["Staff", "Staff"], "D uses the active weapon, every press (the weapon's script toggles)")
    inv.toggle(s); check(inv.cursor == 2, "the list opens on the active weapon"); inv.key(ord("1"), s); check(inv.active == "Hat" and inv.open, "a digit picks that weapon")
    inv.key(ord("d"), s); check(s.runner.fired[-1] == "Hat" and not inv.open, "D inside the list uses it and closes"); inv.toggle(s); inv.key(ord("q"), s); check(not inv.open, "Q closes")
    inv.toggle(s); px, py, pw = 16, 16, 330; y0 = py + 28 + inv._stats_h(s)
    check(inv.click(px + 50, y0 + 20 + 5, s) and inv.active == "Dragon" and not inv.open, "a click on the second row picks it")
    check(not inv.click(5, 5, s), "a closed list ignores clicks")
    s.runner.ws.pop(1); inv.active = "Dragon"; check(inv.fire(s) is None, "the active weapon was removed (PLO_NPCWEAPONDEL): D does nothing")
    inv.toggle(s); out = Image.new("RGBA", (640, 480)); inv.draw(out, s); check(out.getbbox() is not None, "the list draws")
    check("Q" in inv.status(s), "status line")
    print("inventory tests passed")

if __name__ == "__main__": main()
