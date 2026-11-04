"""Tile definitions: addtiledef (whole tileset by level prefix, any case), addtiledef2 (pasted at x,y), #L (this level only), removetiledefs; and a new gmap world drops the old one's NPCs."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from PIL import Image
import assets, render

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    d = tempfile.mkdtemp()
    Image.new("RGBA", (2048, 512), (255, 0, 0, 255)).save(os.path.join(d, "zz_main.png")); Image.new("RGBA", (96, 128), (0, 0, 255, 255)).save(os.path.join(d, "zz_over.png"))
    for f in ("zz_main.png", "zz_over.png"): assets.arrived(f, os.path.join(d, f))
    tw = "addtiledef zz_main.png,Val_Hell,1;\naddtiledef2 zz_over.png,val_hell,1760,352;"
    ts = render.tileset_for("val_hellsreach_a.nw", tw, [])
    check(ts.getpixel((10, 10)) == (255, 0, 0, 255) and ts.getpixel((1770, 360)) == (0, 0, 255, 255) and ts.getpixel((1700, 360)) == (255, 0, 0, 255), "prefix match in any case: tileset, then the overlay at x,y")
    check(render.tileset_for("other_a.nw", tw, []).getpixel((10, 10)) != (255, 0, 0, 255), "another level keeps the default tileset")
    ts3 = render.tileset_for("val_hellsreach_a.nw", "", ["addtiledef zz_main.png,#L,0;\naddtiledef2 zz_over.png,#L,0,0;"])
    check(ts3.getpixel((10, 10)) == (0, 0, 255, 255) and ts3.getpixel((100, 100)) == (255, 0, 0, 255), "#L: this level's own two tilesets, the overlay on top")
    check(render.tileset_for("val_hellsreach_a.nw", tw + "\nremovetiledefs;", []).getpixel((10, 10)) != (255, 0, 0, 255), "removetiledefs")
    check(render.tileset_for("val_hellsreach_a.nw", tw, []) is render.tileset_for("val_hellsreach_a.nw", tw, []), "the canvas is cached")
    blk = "/* addtiledef zz_main.png,Old_,0;\n   addtiledef2 zz_over.png,Old_,1760,352; */\n  //addtiledef zz_main.png,Old_,0;\naddtiledef2 zz_over.png,New_,0,0;"
    check([c[2] for c in render._tiledef_cmds(blk)] == ["New_"], "tiledef lines inside /* */ and // comments are not commands (the TileDefs weapon has 37 of them in block comments)")
    # addtiledef2: a smaller picture goes on top of a larger one (greendale-pub_1 writes the small one first, then a full-width one at 0,0).
    import render as _r
    from PIL import Image as _I
    _r._img_cache["zz-small.png"] = _I.new("RGBA", (16, 16), (255, 0, 0, 255)); _r._img_cache["zz-full.png"] = _I.new("RGBA", (2048, 512), (0, 0, 255, 255))
    _ts = _r.tileset_for("zz-room.nw", "", ["removetiledefs;\naddtiledef2 zz-small.png,#L,1024,0;\naddtiledef2 zz-full.png,#L,0,0;"])
    assert _ts.getpixel((1030, 5)) == (255, 0, 0, 255) and _ts.getpixel((10, 5)) == (0, 0, 255, 255), "the small picture written first stays on top of the full-width one written after it"
    # ... and the other way round (portwolfe_b2): the full-width picture first, then small pieces - a smaller picture is never hidden by a larger one.
    _ts = _r.tileset_for("zz-room2.nw", "", ["removetiledefs;\naddtiledef2 zz-full.png,#L,0,0;\naddtiledef2 zz-small.png,#L,1024,0;"])
    assert _ts.getpixel((1030, 5)) == (255, 0, 0, 255) and _ts.getpixel((10, 5)) == (0, 0, 255, 255), "small pieces after a full-width picture stay visible"
    # Prefixed tiledefs stay registered when you walk on: portwolfe_a1 registers addtiledef2 ...,portwolfe_,... and portwolfe_alley2 (a plain level) has none of its own.
    import gclient as _g
    _r._img_cache["zz-green.png"] = _I.new("RGBA", (16, 16), (0, 255, 0, 255))
    _G = _g.Session.__new__(_g.Session); _g.Session.__init__(_G, "a", "b", "222", ("127.0.0.1", 1)); _G.send = lambda l: None
    _G.gmap, _G.level_name = "zzport.gmap", "zzport_a1.nw"
    _G.npcs = {1: {"SCRIPT": "//#CLIENTSIDE\nif (created) {\n  addtiledef2 zz-green.png,zzport_,1024,0;\n  addtiledef2 zz-full.png, #L,0,0;\n  removetiledefs;\n}"}}
    _G._enter_world("zzport_alley2.nw")
    mem = _G.snapshot()["tiledef_memory"]
    assert mem == ["addtiledef2 zz-green.png,zzport_,1024,0;"], "only the prefixed add line is kept (not #L, not removetiledefs): %r" % mem
    _ts = _r.tileset_for("zzport_alley2.nw", "", [], mem)
    assert _ts.getpixel((1030, 5)) == (0, 255, 0, 255), "a plain level gets the prefixed tiles registered in the level before"
    _o = _r.tileset_for("zzother.nw", "", [], mem)
    assert _o.getpixel((1030, 5)) != (0, 255, 0, 255), "but only levels whose name starts with the prefix"
    print("tiledefs tests passed")

if __name__ == "__main__": main()
