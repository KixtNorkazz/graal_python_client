"""python3 test_effectmode.py : seteffectmode 0 (the default) draws a see-through NPC as light, 1 as transparency (Graal's own list: 0 - as light,
1 - as transparency, 2 - holes). val_smoke-ambience.gif with setcoloreffect .1,.1,.1,.95 must brighten what is under it (a faint white haze), not darken it."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from PIL import Image
import render, offline

def check(c, m):
    if not c: raise AssertionError(m)

def brightness(im, box):
    h = im.convert("L").crop(box).histogram(); return sum(i * n for i, n in enumerate(h)) / sum(h)

def main():
    render._img_cache["test-haze.png"] = Image.new("RGBA", (64, 64), (230, 230, 230, 255))
    S = offline.OfflineSession("turtlejunction-h4.nw", pos=(480, 700), account="TestA"); S.send = lambda l: None
    size = (640, 456); box = (300, 200, 340, 240)
    def frame(script):
        S.npcs.pop(("p", 1), None)
        if script is not None:
            S.npcs[("p", 1)] = dict(IMAGE="test-haze.png", SCRIPT="//#CLIENTSIDE\nif (created) { dontblock; drawoverplayer; " + script + " }", X2=480 - 320 + 300, Y2=700 + 24 - 228 + 200, LEVEL=S.level_name)
            if S.gmap: S.npcs[("p", 1)]["GMAPLEVELX"], S.npcs[("p", 1)]["GMAPLEVELY"] = S.cell
        render._world_cache.clear(); return render.render_scene(S.snapshot(), size=size, show_lights=False)
    plain = brightness(frame(None), box)
    light = brightness(frame("setcoloreffect .1,.1,.1,.95;"), box)
    trans = brightness(frame("setcoloreffect .1,.1,.1,.95; seteffectmode 1;"), box)
    opaque = brightness(frame("setcoloreffect .1,.1,.1,1;"), box)
    check(light > plain + 5, "mode 0 (default), see-through: added like light, brighter (%.0f -> %.0f)" % (plain, light))
    check(light < plain + 60, "but only a faint haze: colour .1 times alpha .95 (%.0f -> %.0f)" % (plain, light))
    check(trans < plain - 5, "mode 1: ordinary transparency, the dark picture darkens (%.0f -> %.0f)" % (plain, trans))
    check(opaque < 40, "alpha 1: drawn as it is, a dark picture (%.0f)" % opaque)
    print("effect mode tests passed")

main()
