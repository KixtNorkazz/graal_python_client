"""python3 test_render_cull.py : a big NPC picture (a ship, a tree) whose top-left corner is far above or left of the view must still be drawn while part of it shows."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from PIL import Image
import render, gs1

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    render._img_cache["test-ship.png"] = Image.new("RGBA", (400, 500), (200, 50, 50, 255))
    n = dict(IMAGE="test-ship.png", SCRIPT="", X2=0, Y2=0)
    fx = gs1.run("", "test-ship.png", 0, 0)
    size = (640, 456)
    check(render._on_screen(fx, n, 100, -480, size), "a 500 px tall ship 480 px above the view still shows its bottom 20 px")
    check(render._on_screen(fx, n, -390, 100, size), "and one 390 px left of the view its right 10 px")
    check(not render._on_screen(fx, n, 100, -580, size), "but not once it is wholly above the view (with the 64 px margin)")
    check(not render._on_screen(fx, n, 720, 100, size), "nor right of it")
    # The whole frame: a 500 px tall ship whose top-left corner is 480 px above the view (the old code skipped it beyond 300 px).
    import offline
    from PIL import ImageChops
    S = offline.OfflineSession("turtlejunction-h4.nw", pos=(480, 700), account="TestA"); S.send = lambda l: None
    S.npcs[("p", 1)] = dict(IMAGE="test-ship.png", SCRIPT="", X2=300, Y2=700 + 24 - 228 - 480, LEVEL=S.level_name)
    if S.gmap: S.npcs[("p", 1)]["GMAPLEVELX"], S.npcs[("p", 1)]["GMAPLEVELY"] = S.cell
    with_ship = render.render_scene(S.snapshot(), size=size, show_lights=False)
    del S.npcs[("p", 1)]
    without = render.render_scene(S.snapshot(), size=size, show_lights=False)
    check(ImageChops.difference(with_ship.convert("RGB"), without.convert("RGB")).getbbox() is not None, "the ship's bottom is drawn in the frame")
    # A light just right of the view whose glow reaches into it is drawn (lights are culled by their own size, not by the NPC's picture).
    render._img_cache["test-glow.png"] = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    glow = dict(image="test-glow.png", zoom=3.0, color=(1, 1, 1, 1))
    check(render._light_on_screen(render._img_cache["test-glow.png"], glow, size[0] + 50, 100, size), "a glow 3x as big reaches back into the view")
    check(not render._light_on_screen(render._img_cache["test-glow.png"], glow, size[0] + 120, 100, size), "one far enough right does not")
    print("render cull tests passed")

main()
