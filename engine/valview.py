"""python3 valview.py <level.nw|gmap> [out.png]  -> render a RP server level or gmap offline."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
import assets, render, nwlevel

def level_image(name):
    p = assets.find(name)
    if not p: return None, None
    lv = nwlevel.load_nw(p); ts = render.tileset_for(name, "", [n["script"] for n in lv.npcs])
    return render.render_level_tiles(lv.board, ts), lv

def gmap_image(gmap):
    rows = render.read_gmap(gmap); h, w = len(rows), max(len(r) for r in rows)
    out = Image.new("RGBA", (w * 1024, h * 1024), (0, 0, 0, 255)); miss = 0
    for y, r in enumerate(rows):
        for x, n in enumerate(r):
            im, _ = level_image(n) if n else (None, None)
            if im: out.paste(im, (x * 1024, y * 1024))
            else: miss += 1
    return out, miss

if __name__ == "__main__":
    name, dst = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "valview.png")
    if name.endswith(".gmap"): im, miss = gmap_image(name); print("missing levels:", miss)
    else: im, lv = level_image(name); print("links:", len(lv.links), "npcs:", len(lv.npcs))
    im.save(dst)
