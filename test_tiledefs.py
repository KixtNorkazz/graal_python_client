"""Tile definitions: addtiledef (whole tileset by level prefix, any case), addtiledef2 (pasted at x,y), #L (this level only), removetiledefs; and a new gmap world drops the old one's NPCs."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    print("tiledefs tests passed")

if __name__ == "__main__": main()
