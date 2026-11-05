"""python3 test_horses.py : horses and names under the players. A horse sheet (96 x 576) is cut as ride.gani's HORSE sprites (standing row 0,
steps rows 3 and 6; up / down, left, right), a horse on the ground is one frame and not the whole sheet, a rider uses the ride ganis (which draw
the horse), getting on or off switches the gani at once; nicknames are drawn under the characters unless Settings > Player names is off."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from PIL import Image, ImageChops
import render, gclient, settings

def check(c, m):
    if not c: raise AssertionError(m)

def sheet():
    """A test sheet: every 64 px row its own colour, left half and right half different, so a crop shows where it came from."""
    im = Image.new("RGBA", (96, 576))
    for r in range(9):
        im.paste((20 * r + 10, 100, 0, 255), (0, 64 * r, 48, 64 * r + 64)); im.paste((20 * r + 10, 200, 0, 255), (48, 64 * r, 96, 64 * r + 64))
    return im

def main():
    render._img_cache["zz-horse.png"] = sheet(); render._horse_cache.clear()
    def row_of(fr): return (fr.getpixel((2, 2))[0] - 10) // 20
    for g in range(3):
        up, left, down, right = (render.horse_frame("zz-horse.png", d, g) for d in range(4))
        check(up.size == (48, 64) and row_of(up) == 3 * g and up.getpixel((2, 2))[1] == 100, f"step {g}: up is the left half of row {3 * g}")
        check(down.size == (48, 64) and row_of(down) == 3 * g and down.getpixel((2, 2))[1] == 200, f"step {g}: down is the right half of row {3 * g}")
        check(left.size == (96, 64) and row_of(left) == 3 * g + 1, f"step {g}: left is row {3 * g + 1} (not a row of up / down pairs)")
        check(right.size == (96, 64) and row_of(right) == 3 * g + 2, f"step {g}: right is row {3 * g + 2}, its own row, not the left one mirrored")

    # A rider: the ride ganis (in engine/builtin) draw the horse from HORSEIMAGE.
    check(render._has_horse("ride") and render._has_horse("ridestill") and not render._has_horse("idle"), "ride / ridestill draw a HORSE sprite")
    props = {"HORSEIMAGE": "zz-horse.png", "HEADIMAGE": "", "BODYIMAGE": ""}
    c = Image.new("RGBA", (200, 200)); render.draw_character(c, "ridestill", 2, props, 60, 60, 0.0)
    g_, a_ = c.getchannel("G"), c.getchannel("A")
    check(ImageChops.multiply(g_.point(lambda v: 255 if v == 200 else 0), a_.point(lambda v: 255 if v == 255 else 0)).getbbox() is not None, "the horse (facing down: the sheet's right half) is drawn by the gani")

    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    s.level_name = "zz.nw"; s.gmap = None; s.pos = (480, 480)
    check(s.resolve_ani("walk") == "walk" and s.resolve_ani("idle") == "idle", "on foot: walk / idle")
    s.horses.append(("zz-horse.png", 30.0, 30.0, (0, 0))); s.pos = (472, 456)
    check(s.horse_touch() and s.me["HORSEIMAGE"] == "zz-horse.png" and s.me["GANI"] == "ridestill", f"walking into a horse mounts it, standing gani ridestill: {s.me.get('GANI')}")
    check(any(b"ridestill" in l for l in sent), "and the others are told")
    check(s.resolve_ani("walk") == "ride" and s.resolve_ani("sword") == "ridesword" and s.resolve_ani("hurt") == "ridehurt", "on a horse: ride / ridesword / ridehurt")
    # Riding: ridestill must not be ended and restarted as a one-shot gani (each restart held the gani for 0.3 s, so walking never showed ride).
    import time as _t
    s.gani_start = _t.time() - 5; s.update_gani(); check(s.me["GANI"] == "ridestill" and _t.time() >= s.weapon_ani_until, "ridestill stays, nothing holds the gani")
    s.step("L", True); check(s.me["GANI"] == "ride", f"walking on the horse: ride ({s.me['GANI']})")
    s.gani_start = _t.time() - 5; s.update_gani(); check(s.me["GANI"] == "ride", "and it keeps riding")
    # D on a horse gets off it (unless the active weapon is used while riding: firedonhorse).
    import inventory, weapons
    inv = inventory.Inventory(); s.runner.weapons.clear()
    s.runner.weapons["Zz Bow"] = weapons.Weapon("Zz Bow", "", "if (weaponfired) { setplayerprop #c,bang; }", s); inv.active = "Zz Bow"
    s.runner.weapons["Zz Lance"] = weapons.Weapon("Zz Lance", "", "if (weaponfired && firedonhorse) { setplayerprop #c,charge; }", s)
    inv.active = "Zz Lance"; check(inv.fire(s) != "dismount" and s.me["HORSEIMAGE"], "a weapon made for riding is used on the horse")
    inv.active = "Zz Bow"; check(inv.fire(s) == "dismount", "D with another weapon gets off")
    check(s.me["GANI"] == "idle" and s.me["HORSEIMAGE"] == "" and len(s.horses[-1]) == 5, "getting off: idle again, the horse stays with its direction")

    # Names under the players.
    import offline
    S = offline.OfflineSession("turtlejunction-h4.nw", pos=(480, 700), account="TestA"); S.send = lambda l: None
    S.me["NICKNAME"] = "Zz Name (Test Guild)"
    settings.apply(S, dict(settings.DEFAULTS, show_names=True)); with_names = render.render_scene(S.snapshot(), size=(640, 456)).convert("RGB")
    settings.apply(S, dict(settings.DEFAULTS, show_names=False)); without = render.render_scene(S.snapshot(), size=(640, 456)).convert("RGB")
    bb = ImageChops.difference(with_names, without).getbbox()
    check(bb is not None and bb[1] > 228 and bb[3] < 228 + 60, f"the name is drawn just under the player (who is in the middle of the view): {bb}")
    check(settings.DEFAULTS["show_names"] is True and ("show_names", "Player names") in settings.ROWS, "Settings has a Player names row, on by default")
    settings.apply(S, settings.DEFAULTS)
    print("horse and name tests passed")

main()
