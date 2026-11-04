"""Offline renderer: builds a 640x480-ish view of the gmap around the player from a Session snapshot (PIL only)."""
import os, re, sys, math, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
import assets, warnings

# Pictures come from the server. A 10 kB PNG can declare 9000x9000 pixels, ~320 MB as RGBA, which gets the app killed on a phone.
# The largest real picture is ~6 million pixels; Pillow refuses anything over twice this limit and warns above it: make that an error too.
Image.MAX_IMAGE_PIXELS = 4096 * 4096
warnings.simplefilter("error", Image.DecompressionBombWarning)

TILE = 16
_img_cache = {}

def load_image(name, kind=None):
    key = name.lower()
    if key not in _img_cache:
        p = assets.find(name, kind=kind); im = None
        for cand in ([p] + [c for c in assets.candidates(name) if c != p] if p else []):   # a damaged copy must not hide a good one with the same name
            try: im = Image.open(cand).convert("RGBA"); break
            except Image.DecompressionBombError: break
            except Exception: continue
        if p and im is None: assets.broken(name, kind)   # no local copy can be read: fetch it from the server
        _img_cache[key] = im
    return _img_cache[key]

_horse_cache = {}

def horse_frame(name, direction, step=0):
    """Approximate frame of a horse sheet (96 x 576 = 9 rows of 64 px: row 0 up / down views 48 px wide, rows 1.. side views 96 px wide, facing left; the original client's
    frame table is not known, this is read off the sheets). direction 0 up, 1 left, 2 down, 3 right (mirrored side view)."""
    key = (name, direction, step % 3)
    if key not in _horse_cache:
        sheet = load_image(name); fr = None
        if sheet is not None and sheet.height >= 128:
            if direction == 0: fr = sheet.crop((0, 0, 48, 64))
            elif direction == 2: fr = sheet.crop((48, 0, 96, 64))
            else:
                fr = sheet.crop((0, 64 * (1 + step % 3), 96, 64 * (2 + step % 3)))
                if direction == 3: fr = fr.transpose(Image.FLIP_LEFT_RIGHT)
        _horse_cache[key] = fr
    return _horse_cache[key]

_gmap_cache = {}

def _forget_missing(key=None):
    for c in (_img_cache, _horse_cache, _item_cache):
        for k in [k for k, v in c.items() if v is None]: del c[k]
    _clear_tile_caches()
    _horse_cache.clear(); _world_cache.clear(); _fx_cache.clear()
assets.listeners.append(_forget_missing)

def read_gmap(name):
    """rows[y][x] = level name. Cached per file and modification time (the collision code asks for it on every blocked() call). The file is looked at
    on disk at most once a second: os.stat is cheap on Linux but slow on Windows (more so in a OneDrive folder with the virus scanner), and with
    6 to 20 calls a frame it held the gmaps at 18-23 fps there."""
    p = assets.find(name)
    if not p: return []
    c = _gmap_cache.get(p); now = time.monotonic()
    if c and now - c[2] < 1.0: return c[1]
    try: stamp = os.stat(p).st_mtime
    except OSError: stamp = None
    if c and c[0] == stamp: _gmap_cache[p] = (stamp, c[1], now); return c[1]
    rows = []; inside = False
    for ln in open(p, encoding="latin1"):
        s_ = ln.strip()
        if s_ == "LEVELNAMES": inside = True; continue
        if s_ == "LEVELNAMESEND": inside = False; continue
        if s_.startswith('"') or (inside and s_): rows.append([x.strip().strip('"') for x in s_.split(",")])
    _gmap_cache[p] = (stamp, rows, now); return rows

BASE_TILESET = os.environ.get("GRAAL_BASE_TILESET") or "pics1.png"

def tile_src(t):
    return (t % 16) * 16 + (t // 512) * 256, ((t // 16) % 32) * 16

_TILEDEF_CMD = re.compile(r"\b(addtiledef2?|removetiledefs)\b([^;{}\n]*)")

_cmds_cache = {}

def _tiledef_cmds(text):
    """Ordered tiledef commands of a script: ('add', image, prefix, x, y) / ('remove', prefix_or_None). Cached per script text: on a gmap
    tileset_for reads the TileDefs weapon (80 kB) and every NPC script for each of the 25 cells around on every frame (5.5 ms here, three times that
    on Windows), and the scripts hardly ever change."""
    text = text or ""
    got = _cmds_cache.get(text)
    if got is None:
        if len(_cmds_cache) > 4000: _cmds_cache.clear()
        got = _cmds_cache[text] = tuple(_parse_tiledef_cmds(text))
    return got

def _parse_tiledef_cmds(text):
    for m in _TILEDEF_CMD.finditer(re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text or "", flags=re.S))):
        name, rest = m.group(1), [a.strip() for a in m.group(2).split(",")]
        if name == "removetiledefs": yield ("remove", rest[0] or None); continue
        if len(rest) >= 3 and rest[0] and rest[1]:
            try: yield ("add", rest[0], rest[1], int(rest[2]), int(rest[3]) if len(rest) > 3 and name == "addtiledef2" else 0, name == "addtiledef2")
            except ValueError: pass

_ts_cache = {}
_tile_img = {}
_level_img = {}

def _clear_tile_caches():
    _ts_cache.clear(); _tile_img.clear(); _level_img.clear()

def tileset_for(level_name, tiledef_script, npc_scripts, other_scripts=(), base=None):
    """Default pics1.png, then tiledefs in order: the TileDefs weapon and the NPC scripts of other loaded levels (prefix match only), then
    this level's own NPC scripts (prefix match or #L). `removetiledefs` (optionally with a prefix) drops what was registered before it.
    The canvas is cached by what was applied, so crossing into a level with the same tiles costs nothing."""
    defs = []
    def feed(cmds, own):
        for c in cmds:
            if c[0] == "remove":
                defs[:] = [] if c[1] is None else [d for d in defs if not d[1].lower().startswith(c[1].lower())]
            elif c[2] != "#L" or own: defs.append(c[1:])
    feed(_tiledef_cmds(tiledef_script), False)
    for sc in other_scripts: feed(_tiledef_cmds(sc), False)
    for sc in npc_scripts: feed(_tiledef_cmds(sc), True)
    lname = level_name.lower()
    applied = [(img, a, b, two) for img, prefix, a, b, two in defs if prefix == "#L" or lname.startswith(prefix.lower())]
    base_name = base or BASE_TILESET; base = load_image(base_name, "tilesets"); ims = [load_image(d[0], "tilesets") for d in applied]
    key = (base_name.lower(), base is not None, tuple((d, im is not None) for d, im in zip(applied, ims)))
    c = _ts_cache.get(key)
    if c is not None: return c
    canvas = Image.new("RGBA", (2048, 512))
    if base: canvas.paste(base, (0, 0))
    # addtiledef (a whole tileset) is the bottom layer, the last one winning. addtiledef2 pictures go on top of it, the larger ones first, so a smaller
    # picture is never hidden by a larger one; pictures of the same size keep their order (the later one on top). Levels write them in both orders:
    # greendale-pub_1 the small one first (addtiledef2 val_frost-insides.png,#L,1024,0; addtiledef2 sighisoara-tiles.png,#L,0,0), portwolfe_b2 the
    # full-width one first and then twelve small lacuna_extracrap pieces - "the last one wins" broke the pub, "the first one wins" broke portwolfe.
    for (img, a, b, two), im in zip(applied, ims):
        if im and not two: canvas.paste(im, (0, 0))
    overlays = [(im, a, b) for (img, a, b, two), im in zip(applied, ims) if im and two]
    for im, a, b in sorted(overlays, key=lambda o: -o[0].width * o[0].height):
        canvas.paste(im, (a, b))
    if len(_ts_cache) >= 24: _clear_tile_caches()
    _ts_cache[key] = canvas; return canvas

def render_level_tiles(board, tileset):
    out = Image.new("RGBA", (1024, 1024)); tid = id(tileset); cache = _tile_img
    for ty in range(64):
        for tx in range(64):
            i = 2 * (ty * 64 + tx); t = (board[i] | (board[i + 1] << 8)) & 0xFFF
            im = cache.get((tid, t))
            if im is None:
                sx, sy = tile_src(t); im = cache[(tid, t)] = tileset.crop((sx, sy, sx + 16, sy + 16))
            out.paste(im, (tx * 16, ty * 16))
    return out

def level_image(name, lv, tileset):
    """The tiles of a level as one 1024x1024 image, cached per board version and tileset."""
    key = (name, getattr(lv, "version", 0), id(tileset)); im = _level_img.get(key)
    if im is None:
        if len(_level_img) >= 40: _level_img.clear()
        im = _level_img[key] = render_level_tiles(lv.board, tileset)
    return im

def _gmap_scripts(npcs):
    scripts = collections.defaultdict(list)
    for n in npcs.values():
        if n.get("SCRIPT") and "GMAPLEVELX" in n: scripts[(n["GMAPLEVELX"], n["GMAPLEVELY"])].append(n["SCRIPT"])
    return scripts

_prebuild_done = {}

def prebuild_one(levels, npcs, weapons, gmap_name, cur_level, radius=2, remembered=(), rev=None):
    """Build the image of one level near us that has its board but no image yet (a ring of `radius` cells), so that walking into it later costs nothing.
    Returns True if something was built (call again in the next idle moment). Once it has found nothing to build it does not look again until
    something it depends on changes (`rev`: the session's npc_rev; the viewer calls it on every frame and the look costs 25 tilesets)."""
    if not gmap_name: return False
    sig = (gmap_name, cur_level, radius, rev, id(npcs), len(npcs), len(weapons.get("TileDefs", b"")), len(remembered),
           tuple(sorted((n, getattr(l, "version", 0), bool(l.board)) for n, l in levels.items())), len(_level_img))
    if rev is not None and _prebuild_done.get("sig") == sig: return False
    rows = read_gmap(gmap_name); pos = {n: (x, y) for y, r in enumerate(rows) for x, n in enumerate(r)}
    if cur_level not in pos: return False
    cx, cy = pos[cur_level]; tiledefs = weapons.get("TileDefs", b"").replace(b"\xa7", b"\n").decode("latin1"); scripts = _gmap_scripts(npcs)
    for dy, dx in sorted(((dy, dx) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)), key=lambda d: abs(d[0]) + abs(d[1])):
        x, y = cx + dx, cy + dy
        if not (0 <= y < len(rows) and 0 <= x < len(rows[0])): continue
        name = rows[y][x]; lv = levels.get(name)
        if not lv or not lv.board: continue
        ts = tileset_for(name, tiledefs, scripts[(x, y)], list(remembered) + [sc for k, v in scripts.items() if k != (x, y) for sc in v])
        if (name, getattr(lv, "version", 0), id(ts)) not in _level_img: level_image(name, lv, ts); return True
    _prebuild_done["sig"] = sig; return False

def build_world_image(levels, npcs, weapons, gmap_name, cur_level, radius=1, remembered=()):
    """Stitch the tiles of the current sub-level and its neighbours. Returns (image, origin_px_of_cur_level, cell_of_cur)."""
    rows = read_gmap(gmap_name); pos = {n: (x, y) for y, r in enumerate(rows) for x, n in enumerate(r)}
    cx, cy = pos[cur_level]
    tiledefs = weapons.get("TileDefs", b"").replace(b"\xa7", b"\n").decode("latin1")
    scripts = _gmap_scripts(npcs)
    size = 2 * radius + 1; world = Image.new("RGBA", (size * 1024, size * 1024))
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = cx + dx, cy + dy
            if not (0 <= y < len(rows) and 0 <= x < len(rows[0])): continue
            name = rows[y][x]; lv = levels.get(name)
            if not lv or not lv.board: continue
            ts = tileset_for(name, tiledefs, scripts[(x, y)], list(remembered) + [sc for k, v in scripts.items() if k != (x, y) for sc in v])
            world.paste(level_image(name, lv, ts), ((dx + radius) * 1024, (dy + radius) * 1024))
            _world_cache.setdefault("pending", {})[name] = ((dx + radius) * 1024, (dy + radius) * 1024, ts)
    return world, (radius * 1024, radius * 1024), (cx, cy)


import gani as ganimod, gs1
from PIL import ImageChops

def _scaled(im, z):
    if abs(z - 1.0) < 1e-3: return im
    return im.resize((max(1, int(im.width * z)), max(1, int(im.height * z))), Image.NEAREST)

_npc_img_cache, _light_cache = {}, {}

def _tint(im, color):
    r, g, b, a = color; im = im.convert("RGBA")
    R, G, B, A = im.split()
    return Image.merge("RGBA", (R.point(lambda v: int(v * r)), G.point(lambda v: int(v * g)),
                                B.point(lambda v: int(v * b)), A.point(lambda v: int(v * a))))

def draw_character(canvas, gani_name, direction, props, x, y, t=0.0):
    """Draw a player/NPC character with the given gani frame 0 at pixel (x, y)."""
    g = ganimod.load(gani_name) or ganimod.load("idle")
    if not g or not g.frames: return
    frame = g.frames[ganimod.frame_at(g, t)][direction]
    sw = props.get("SHIELDIMAGE") or {}; sd = props.get("SWORDIMAGE") or {}
    def source(key):
        if key == "BODY": return props.get("BODYIMAGE") or g.defaults.get("DEFAULTBODY", "body.png")
        if key == "HEAD": return props.get("HEADIMAGE") or g.defaults.get("DEFAULTHEAD", "head0.png")
        if key == "SHIELD": return sw.get("image") or ""
        if key == "SWORD": return sd.get("image") or ""
        m = re.fullmatch(r"ATTR(\d+)", key)
        if m: return props.get(f"GATTRIB{m.group(1)}") or ""
        if key == "SPRITES": return "sprites.png"
        if key == "PICS": return "pics1.png"
        return key
    for idx, ox, oy in frame:
        spr = g.sprites.get(idx)
        if not spr: continue
        name = source(spr[0]); im = load_image(name, PART_KIND.get(spr[0], "hats" if spr[0] == "ATTR1" else None)) if name else None
        if im is None: continue
        _, sx, sy, w, h = spr
        canvas.alpha_composite(im.crop((sx, sy, sx + w, sy + h)), (int(x + ox), int(y + oy))) if (
            0 <= x + ox < canvas.width and 0 <= y + oy < canvas.height) else _paste_clipped(canvas, im.crop((sx, sy, sx + w, sy + h)), int(x + ox), int(y + oy))

PART_KIND = {"HEAD": "heads", "BODY": "bodies", "SWORD": "swords", "SHIELD": "shields"}   # gani sprite source -> folder of the world

_hard_alpha = {}

def _paste_clipped(canvas, im, x, y):
    """Alpha-composite `im` at (x, y), only the part that lies inside the canvas (no full-size temporary layer). A picture whose pixels are all
    either fully see-through or fully solid (most GIFs) is pasted through its own alpha as a mask instead: one call, about twice as fast, and
    the same pixels in every channel. Pictures with partly see-through pixels go through alpha_composite as before."""
    cw, ch = canvas.size; w, h = im.size
    x0, y0, x1, y1 = max(0, x), max(0, y), min(cw, x + w), min(ch, y + h)
    if x1 <= x0 or y1 <= y0: return
    if im.mode != "RGBA": im = im.convert("RGBA")
    hard = _hard_alpha.get(id(im))
    if hard is None or hard[0] is not im:
        hist = im.getchannel("A").histogram(); hard = (im, sum(hist[1:255]) == 0)
        if len(_hard_alpha) > 2000: _hard_alpha.clear()
        _hard_alpha[id(im)] = hard
    if hard[1]: canvas.paste(im, (x, y), im)
    else: canvas.alpha_composite(im.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))

def _light_tint(color):
    """setcoloreffect r,g,b,a of a picture drawn as light (seteffectmode 0, see-through): adding colour*alpha to what is under it is drawn as a blend
    towards the picture's colour scaled to full strength, with the alpha scaled down to match. Over a dark ground that is the same as adding; over a
    bright one a little weaker. It is an ordinary tint, so it is worked out once per picture and not on every frame (the smoke is drawn every frame)."""
    r, g, b, a = color; k = max(r, g, b)
    if k <= 0: return (0, 0, 0, 0)
    return (r / k, g / k, b / k, min(1.0, a * k))

from PIL import ImageDraw, ImageFont
_font = None
def draw_chat(view, text, cx, bottom_y):
    """Text above a character's head: white with a dark outline, centred on cx (bitmap font: this Pillow has no FreeType)."""
    global _font
    if _font is None:
        try: _font = ImageFont.load_default(size=12)
        except Exception: _font = ImageFont.load_default()
    d = ImageDraw.Draw(view); w = d.textlength(text, font=_font)
    x, y = int(cx - w / 2), int(bottom_y - 14)
    for ox_, oy_ in ((-1, 0), (1, 0), (0, -1), (0, 1)): d.text((x + ox_, y + oy_), text, font=_font, fill=(0, 0, 0, 255))
    d.text((x, y), text, font=_font, fill=(255, 255, 255, 255))

_world_cache = {}
_fx_cache = {}

_ITEM_WINDOWS = {0: (0, 143, 16, 32), 1: (16, 143, 16, 32), 2: (32, 143, 16, 32), 19: (48, 143, 16, 32),
                 3: (64, 143, 16, 20), 4: (82, 141, 18, 26), 5: (42, 176, 18, 16), 11: (16, 176, 26, 28),
                 6: (0, 214, 28, 32), 16: (30, 214, 28, 32), 7: (56, 214, 14, 32), 8: (72, 218, 26, 28)}
_item_cache = {}
def item_sprite(t):
    if t not in _item_cache:
        sheet = load_image("sprites.png"); im = None
        if sheet is not None and t in _ITEM_WINDOWS:
            x, y, w, h = _ITEM_WINDOWS[t]; win = sheet.crop((x, y, x + w, y + h)); bb = win.split()[3].getbbox()
            if bb: im = win.crop(bb)
        if im is None:
            im = Image.new("RGBA", (10, 10), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse((1, 1, 8, 8), fill=(255, 200, 40, 255), outline=(120, 80, 0, 255))
        _item_cache[t] = im
    return _item_cache[t]

_npc_reach = {"t": 0.0}

def _reach(fx, n, dx, dy):
    """How far (px) from its X2/Y2 an NPC can draw anything: its picture (zoomed), how far its script moved it, its showimg lights. Lets
    render_scene skip NPCs far off screen without running their effects: a gmap such as portwolfe has over a thousand NPCs."""
    r = 64 + abs(dx) + abs(dy)
    name = fx.image; im = load_image(name) if name and name not in ("-", "#c#") else None
    if im is not None: r += max(im.size) * max(1.0, fx.zoom)
    for idx, s_ in fx.shows.items():
        if idx >= 200 or "em" in s_: return 10 ** 9   # screen-space pictures and particle emitters: always looked at (as before)
        try: r = max(r, 64 + abs(s_["x"] * 16 - n["X2"]) + abs(s_["y"] * 16 - n["Y2"]) + 512)
        except (KeyError, TypeError): r = 1024
    return min(1024, int(r))

_cand = {"key": None}
CAND_SLACK = 256

def _candidates(npcs, gmap, cur, cx, cy, ox, oy, camx, camy, size, now, rev=None):
    """The NPCs that can be near the view: the coarse test of render_scene with CAND_SLACK px to spare, worked out again only when the camera has
    moved more than that, the NPCs changed, or a second has passed. A gmap has a thousand NPCs and the phone spent milliseconds a frame just
    looking at each of them; render_scene still makes its own exact test for every one returned."""
    wx, wy = cx * 1024 + camx - ox, cy * 1024 + camy - oy   # the camera in whole-map pixels
    key = (id(npcs), len(npcs), rev, gmap, cur, size)   # rev: the session's count of NPCs added, removed or given a new script
    c = _cand
    if c["key"] == key and abs(wx - c["x"]) < CAND_SLACK and abs(wy - c["y"]) < CAND_SLACK and 0 <= now - c["t"] < 1.0: return c["list"]
    out = []
    for nid, n in npcs.items():
        if "X2" not in n or (gmap and "GMAPLEVELX" not in n): continue
        m = _npc_reach.get(nid, 1024) + CAND_SLACK
        gx = ox + (n.get("GMAPLEVELX", cx) - cx) * 1024 + n["X2"] - camx; gy = oy + (n.get("GMAPLEVELY", cy) - cy) * 1024 + n["Y2"] - camy
        if -m < gx < size[0] + m and -m < gy < size[1] + m: out.append(nid)   # the id only: an NPC can be replaced under the same id
    c.update(key=key, x=wx, y=wy, t=now, list=out); return out

def _on_screen(fx, n, x, y, size):
    """Does any part of the NPC's picture fall inside the view? Its position is the picture's top-left corner, and pictures such as a ship or a
    tree are several hundred pixels big: a fixed margin made them vanish while most of them was still on screen."""
    name = fx.image
    im = load_image(name) if name and name not in ("-", "#c#") and not fx.hidden else None
    if im is None: w = h = 64
    else:
        part = n.get("IMAGEPART")
        if fx.imgpart: w, h = fx.imgpart[3], fx.imgpart[4]
        elif part and part["w"] and part["h"]: w, h = part["w"], part["h"]
        else: w, h = im.size
        if fx.zoom != 1.0: x -= w * (fx.zoom - 1) / 2; y -= h * (fx.zoom - 1) / 2; w *= fx.zoom; h *= fx.zoom
    return x + w > -64 and y + h > -64 and x < size[0] + 64 and y < size[1] + 64


def _light_on_screen(im, s, x, y, size):
    """Does a showimg light (scaled around its centre, maybe rotated) reach into the view? Checked before the costly scale/tint work."""
    w, h = im.width * s["zoom"], im.height * s["zoom"]
    if s.get("rot"): w = h = math.hypot(w, h)
    x -= (w - im.width) / 2; y -= (h - im.height) / 2
    return x + w > 0 and y + h > 0 and x < size[0] and y < size[1]


def render_scene(snap, size=(640, 456), cam_offset=(24, 24), radius=1, show_lights=True, t=0.0):
    levels, npcs, weapons, me = snap["levels"], snap["npcs"], snap["weapons"], snap["me"]
    gmap, cur = snap["gmap"], snap["level"]
    if gmap and cur not in {n for r in read_gmap(gmap) for n in r}: gmap = None
    remembered = snap.get("tiledef_memory") or ()   # prefixed tiledefs of levels we were in before (gclient._remember_tiledefs)
    tdsig = (len(remembered), len(weapons.get("TileDefs", b"")), (snap["npc_rev"] if "npc_rev" in snap else sum(len(n.get("SCRIPT", "")) for n in npcs.values())), tuple(sorted(snap.get("adjacent", []))) if not gmap else ())
    key = (gmap, cur, tuple(sorted((n, getattr(l, "version", 0)) for n, l in levels.items() if l.board)), len(npcs), tdsig)
    if _world_cache.get("key") == key:
        world, (ox, oy), (cx, cy) = _world_cache["val"]
        for name, (px_, py_, ts_) in _world_cache["places"].items():
            lv = levels.get(name)
            if lv and lv.board and _world_cache["versions"].get(name) != getattr(lv, "version", 0):
                world.paste(level_image(name, lv, ts_), (px_, py_)); _world_cache["versions"][name] = getattr(lv, "version", 0)
    else:
        if gmap:
            world, (ox, oy), (cx, cy) = build_world_image(levels, npcs, weapons, gmap, cur, radius, remembered)
        else:
            scripts = [n["SCRIPT"] for n in npcs.values() if n.get("SCRIPT")]
            tdefs = weapons.get("TileDefs", b"").replace(b"\xa7", b"\n").decode("latin1")
            lv = levels[cur]; ts = tileset_for(cur, tdefs, scripts, remembered)
            world = Image.new("RGBA", (3072, 3072), (0, 0, 0, 255))
            for nname, nox, noy in snap.get("adjacent", []):
                nlv = levels.get(nname)
                if nlv and nlv.board: world.paste(level_image(nname, nlv, tileset_for(nname, tdefs, [], list(remembered) + scripts)), (1024 + int(nox * 16), 1024 + int(noy * 16)))
            world.paste(level_image(cur, lv, ts), (1024, 1024))
            ox = oy = 1024; first = next(iter(npcs.values()), {}); cx, cy = first.get("GMAPLEVELX", 0), first.get("GMAPLEVELY", 0)
        places = _world_cache.pop("pending", {})
        if not gmap:
            places = {cur: (1024, 1024, ts)}
        _world_cache.update(key=key, val=(world, (ox, oy), (cx, cy)), places=places,
                            versions={n: getattr(levels[n], "version", 0) for n in places if n in levels})
    px, py = me["X2"], me["Y2"]
    camx = ox + px + cam_offset[0] - size[0] // 2; camy = oy + py + cam_offset[1] - (size[1] // 2)
    if snap.get("focus"): camx = ox + snap["focus"][0] - cx * 1024 - size[0] // 2; camy = oy + snap["focus"][1] - cy * 1024 - size[1] // 2
    view = world.crop((camx, camy, camx + size[0], camy + size[1]))
    under, normal, over, lights, with_shows = [], [], [], [], []
    now_ = time.monotonic()
    if now_ - _npc_reach["t"] > 1.0: _npc_reach.clear(); _npc_reach["t"] = now_   # looked at again every second (pictures and scripts change)
    for nid in _candidates(npcs, gmap, cur, cx, cy, ox, oy, camx, camy, size, now_, snap.get("npc_rev")):
        n = npcs.get(nid)
        if n is None or "X2" not in n or (gmap and "GMAPLEVELX" not in n): continue
        ncx, ncy = n.get("GMAPLEVELX", cx), n.get("GMAPLEVELY", cy)
        gx = ox + (ncx - cx) * 1024 + n["X2"] - camx; gy = oy + (ncy - cy) * 1024 + n["Y2"] - camy
        m = _npc_reach.get(nid, 1024)   # coarse; pictures and lights are checked one by one below
        if not (-m < gx < size[0] + m and -m < gy < size[1] + m): continue
        if snap.get("fx"): fx = snap["fx"](nid, n)
        else:
            fkey = (nid, n.get("SCRIPT", ""), n.get("IMAGE", ""), n["X2"], n["Y2"])
            fx = _fx_cache.get(fkey)
            if fx is None: fx = _fx_cache[fkey] = gs1.run(n.get("SCRIPT", ""), n.get("IMAGE", ""), n["X2"] / 16, n["Y2"] / 16)
        if fx.hidden or not n.get("VISFLAGS", 1) & 1: pass
        dx, dy = (fx.x - n["X2"] / 16) * 16, (fx.y - n["Y2"] / 16) * 16
        if nid not in _npc_reach: _npc_reach[nid] = _reach(fx, n, dx, dy)
        if fx.shows: with_shows.append((nid, n, fx))
        for k, s_ in fx.shows.items():
            lights.append((gx + (s_["x"] - n["X2"] / 16) * 16, gy + (s_["y"] - n["Y2"] / 16) * 16, s_))
        if not _on_screen(fx, n, gx + dx, gy + dy, size): continue
        item = dict(n=n, fx=fx, gx=gx + dx, gy=gy + dy, key=gy + dy)
        vf = n.get("VISFLAGS", 0)
        if fx.under or vf & 4: under.append(item)
        elif fx.over or vf & 2: over.append(item)
        else: normal.append(item)
    def draw_npc(it):
        n, fx = it["n"], it["fx"]; name = fx.image
        if not name or name in ("-", "#c#") or fx.hidden: return
        im = load_image(name)
        if im is None: return
        part = n.get("IMAGEPART"); box = None
        if fx.imgpart: _, a, b, c, d = fx.imgpart; box = (a, b, a + c, b + d)
        elif part and part["w"] and part["h"]: box = (part["x"], part["y"], part["x"] + part["w"], part["y"] + part["h"])
        # seteffectmode: 0 = as light (the default), 1 = as transparency, 2 = holes. The mode only matters for a see-through picture (setcoloreffect
        # alpha below 1): lights, fire, window glow and smoke (val_smoke-ambience .1,.1,.1,.95 is a faint white haze, not a black cloud) are added
        # to what is under them; mode 1 (shadows, water) is ordinary transparency. Mode 2 is drawn as transparency too (no darkness to cut holes in).
        color = fx.color
        if color and fx.mode == 0 and color[3] < 1: color = _light_tint(color)
        gx, gy = it["gx"], it["gy"]
        if box or color or fx.zoom != 1.0:
            key = (name, id(im), box, tuple(color) if color else None, fx.zoom); got = _npc_img_cache.get(key)
            if got is None:
                got = im.crop(box) if box else im
                if color: got = _tint(got, color)
                got = _scaled(got, fx.zoom)
                if len(_npc_img_cache) > 400: _npc_img_cache.clear()
                _npc_img_cache[key] = got
            w0, h0 = (box[2] - box[0], box[3] - box[1]) if box else im.size
            im = got; gx -= (im.width - w0) / 2; gy -= (im.height - h0) / 2
        _paste_clipped(view, im, int(gx), int(gy))
    for it in sorted(under, key=lambda i: i["key"]): draw_npc(it)
    for item in snap.get("items", []):
        sp = item_sprite(item["type"])
        ix = ox + (item["cx"] - cx) * 1024 + item["x"] - camx + 8 - sp.width // 2
        iy = oy + (item["cy"] - cy) * 1024 + item["y"] - camy + 16 - sp.height
        _paste_clipped(view, sp, int(ix), int(iy))
    for pj in snap.get("projectiles", []):
        sx = ox - cx * 1024 + pj["gx"] - camx; sy = oy - cy * 1024 + pj["gy"] - camy - pj["z"] * 16
        if -64 < sx < size[0] + 64 and -64 < sy < size[1] + 64 and pj["gani"]:
            draw_character(view, pj["gani"], 0, {}, sx - 8, sy - 8, pj["age"])
    bf = snap.get("bombfx") or {}
    for b in bf.get("bombs", []):
        sp = item_sprite(8); sx = ox - cx * 1024 + b["gx"] - camx + 8 - sp.width // 2; sy = oy - cy * 1024 + b["gy"] - camy + 16 - sp.height
        if b["age"] < 2.0 or int(b["age"] * 8) % 2 == 0: _paste_clipped(view, sp, int(sx), int(sy))
    for bl in bf.get("blasts", []):
        f = min(1.0, bl["f"]); rad = int(bl["r"] * 16 * (0.3 + 0.7 * f)); sx = ox - cx * 1024 + bl["gx"] - camx + 8; sy = oy - cy * 1024 + bl["gy"] - camy + 8
        lay = Image.new("RGBA", view.size, (0, 0, 0, 0)); dr = ImageDraw.Draw(lay)
        dr.ellipse((sx - rad, sy - rad, sx + rad, sy + rad), fill=(255, 120, 20, int(170 * (1 - f))), outline=(255, 230, 120, int(255 * (1 - f))), width=3)
        dr.ellipse((sx - rad // 2, sy - rad // 2, sx + rad // 2, sy + rad // 2), fill=(255, 230, 120, int(200 * (1 - f))))
        view.alpha_composite(lay)
    me_item = dict(key=py + oy - camy + 32, me=True)
    def nkey(i):
        fx = i["fx"]
        if not fx.image: return i["key"] + 32
        if fx.imgpart: return i["key"] + fx.imgpart[4]
        part = i["n"].get("IMAGEPART")
        if part and part.get("h"): return i["key"] + part["h"]
        im = load_image(fx.image); return i["key"] + (im.height if im is not None else 0)
    ents = [(nkey(i), 0, lambda i=i: draw_npc(i)) for i in normal]; bubbles = []
    for it in normal + over:
        n = it["n"]
        if n.get("IMAGE") == "#c#" or it["fx"].showchar:
            ents.append((it["gy"] + 32, 1, lambda n=n, it=it: draw_character(view, (n.get("GANI") or "idle").split(",")[0], (n.get("SPRITE", 2) & 3), n, it["gx"], it["gy"], t)))
    for pid_, pl in snap.get("players", {}).items():
        if "X2" not in pl: continue
        pcx, pcy = pl.get("GMAPLEVELX", cx), pl.get("GMAPLEVELY", cy)
        gx = ox + (pcx - cx) * 1024 + pl["X2"] - camx; gy = oy + (pcy - cy) * 1024 + pl["Y2"] - camy
        ents.append((gy + 32, 2, lambda pl=pl, gx=gx, gy=gy: draw_rider(pl, gx, gy)))
        if pl.get("MESSAGE"): bubbles.append((pl["MESSAGE"], gx + 16, gy + 2))
    for hname, hx, hy, hcell in snap.get("horses", []):
        him = load_image(hname)
        if him is not None:
            hgx = ox + (hcell[0] - cx) * 1024 + hx * 16 - camx; hgy = oy + (hcell[1] - cy) * 1024 + hy * 16 - camy
            ents.append((hgy + him.height, 0, lambda him=him, hgx=hgx, hgy=hgy: _paste_clipped(view, him, int(hgx), int(hgy))))
    def draw_rider(props, gx, gy):
        h = horse_frame(props["HORSEIMAGE"], props.get("SPRITE", 2) & 3, int(t * 6)) if props.get("HORSEIMAGE") else None
        if h is not None:
            _paste_clipped(view, h, int(gx + 16 - h.width // 2), int(gy + 40 - h.height))
            gy -= 12
        draw_character(view, (props.get("GANI") or "idle").split(",")[0], props.get("SPRITE", 2) & 3, props, gx, gy, t)
    ents.append((me_item["key"], 3, lambda: draw_rider(me, ox + px - camx, oy + py - camy)))
    for _, _, fn in sorted(ents, key=lambda e: (e[0], e[1])): fn()
    for b_ in bubbles: draw_chat(view, *b_)
    if me.get("MESSAGE_SHOWN"): draw_chat(view, me["MESSAGE_SHOWN"], ox + px - camx + 16, oy + py - camy + 2)
    for it in sorted(over, key=lambda i: i["key"]): draw_npc(it)
    for it in normal + under + over:
        if it["fx"].message and not it["fx"].hidden: draw_chat(view, it["fx"].message, it["gx"] + 8, it["gy"] + 2)
    for idx, im_ in sorted(snap.get("imgs", {}).items()):
        src = load_image(im_["image"])
        if src is None: continue
        if im_.get("part"): a_, b_, c_, d_ = im_["part"]; src = src.crop((a_, b_, a_ + c_, b_ + d_))
        if im_["color"]: src = _tint(src, im_["color"])
        src = _scaled(src, im_["zoom"])
        if im_.get("rot"): src = src.rotate(-math.degrees(im_["rot"]), expand=True, resample=Image.BICUBIC)
        gx = (im_["x"] if idx >= 200 else ox + im_["x"] * 16 - camx); gy = (im_["y"] if idx >= 200 else oy + im_["y"] * 16 - camy)
        if im_.get("vis") == 3 and idx < 200:
            lay = Image.new("RGB", view.size); lay.paste(src.convert("RGB"), (int(gx), int(gy)))
            view = Image.merge("RGBA", (*ImageChops.add(view.convert("RGB"), lay).split(), view.split()[3]))
        else: _paste_clipped(view, src, int(gx), int(gy))
    if snap.get("effect"):
        r_, g_, b_, a_ = snap["effect"]
        if a_ > 0: view = Image.blend(view.convert("RGB"), Image.new("RGB", view.size, (int(r_ * 255), int(g_ * 255), int(b_ * 255))), min(1.0, a_)).convert("RGBA")
    if show_lights:
        for gx, gy, s in lights:
            im = load_image(s["image"])
            if im is None or not _light_on_screen(im, s, gx, gy, size): continue
            col = tuple(s["color"] or (1, 1, 1, 1)); lkey = (s["image"], id(im), s["zoom"], s.get("rot"), col, bool(s.get("normal"))); got = _light_cache.get(lkey)
            if got is None:
                im = _scaled(im, s["zoom"])
                if s.get("rot"): im = im.rotate(-math.degrees(s["rot"]), expand=True, resample=Image.BICUBIC)
                r, g, b, a = col; R, G, B, A = im.convert("RGBA").split()
                if s.get("normal"): got = Image.merge("RGBA", (R.point(lambda v: int(v * r)), G.point(lambda v: int(v * g)), B.point(lambda v: int(v * b)), A.point(lambda v: int(v * a))))
                else:
                    def lit(c, m, A=A, a=a): return ImageChops.multiply(c, A).point(lambda v: int(min(255, v * m * a)))
                    got = Image.merge("RGB", (lit(R, r), lit(G, g), lit(B, b)))
                if len(_light_cache) > 200: _light_cache.clear()
                _light_cache[lkey] = got
            w0, h0 = load_image(s["image"]).size
            if s.get("normal"):
                _paste_clipped(view, got, int(gx - (got.width - w0) / 2), int(gy - (got.height - h0) / 2)); continue
            tinted = got; im = got
            ax, ay = int(gx - (im.width - w0) / 2), int(gy - (im.height - h0) / 2)
            x0, y0, x1, y1 = max(0, ax), max(0, ay), min(view.width, ax + tinted.width), min(view.height, ay + tinted.height)
            if x1 <= x0 or y1 <= y0: continue
            region = view.crop((x0, y0, x1, y1)); rgb = ImageChops.add(region.convert("RGB"), tinted.crop((x0 - ax, y0 - ay, x1 - ax, y1 - ay)))
            view.paste(Image.merge("RGBA", (*rgb.split(), region.split()[3])), (x0, y0))
    drawn = 0; add_layer = None
    for nid, n, fx in with_shows:   # the NPCs the loop above looked at that show something (it used to ask every NPC of the gmap again here)
        for idx, sh in fx.shows.items():
            em = sh.get("em")
            for p in (em.particles if em else ()):
                if drawn > 600: break
                im = load_image(p["image"])
                if im is None: continue
                base = (ox + (n.get("GMAPLEVELX", cx) - cx) * 1024 - camx, oy + (n.get("GMAPLEVELY", cy) - cy) * 1024 - camy) if idx < 200 else (0, 0)
                px, py = base[0] + p["x"], base[1] + p["y"]
                if not (-128 < px < size[0] + 128 and -128 < py < size[1] + 128): continue
                im = _scaled(im, max(0.02, p["zoom"]))
                if p["rotation"]: im = im.rotate(-math.degrees(p["rotation"]), expand=True, resample=Image.BICUBIC)
                R, G, B, A = im.convert("RGBA").split(); a = max(0.0, min(1.0, p["alpha"]))
                R, G, B = (c.point(lambda v, m=m: int(min(255, v * m * a))) for c, m in zip((R, G, B), (p["red"], p["green"], p["blue"])))
                px, py = int(px - im.width / 2), int(py - im.height / 2)
                if p["mode"] == 0:
                    if add_layer is None: add_layer = Image.new("RGB", view.size)
                    x0, y0 = max(px, 0), max(py, 0); x1, y1 = min(px + im.width, view.width), min(py + im.height, view.height)
                    if x1 > x0 and y1 > y0:
                        box = (x0, y0, x1, y1); src = (x0 - px, y0 - py, x1 - px, y1 - py)
                        piece = ImageChops.multiply(Image.merge("RGB", (R, G, B)).crop(src), Image.merge("RGB", (A, A, A)).crop(src))
                        add_layer.paste(ImageChops.add(add_layer.crop(box), piece), box)
                else: _paste_clipped(view, Image.merge("RGBA", (R, G, B, A.point(lambda v: int(v * a)))), px, py)
                drawn += 1
    if add_layer is not None: view = Image.merge("RGBA", (*ImageChops.add(view.convert("RGB"), add_layer).split(), view.split()[3]))
    return view


def draw_hud(canvas, me, hidden=False):
    """Hearts (full, half, empty up to the maximum) top left, rupee / bomb / arrow counters with their item sprites top right."""
    if hidden: return
    mx = max(int(me.get("FULLHEARTS", 3) or 3), (int(me.get("HALFHEARTS", 0) or 0) + 1) // 2); half = int(me.get("HALFHEARTS", 0) or 0)
    heart = item_sprite(5)
    for k in range(mx):
        x = 8 + k * (heart.width + 2)
        if half >= 2 * (k + 1): canvas.alpha_composite(heart, (x, 6))
        else:
            ghost = heart.copy(); ghost.putalpha(ghost.split()[3].point(lambda a: a // 4)); canvas.alpha_composite(ghost, (x, 6))
            if half == 2 * k + 1: canvas.alpha_composite(heart.crop((0, 0, heart.width // 2, heart.height)), (x, 6))
    d = ImageDraw.Draw(canvas); x = canvas.width - 8
    for typ, key in ((4, "ARROWS"), (3, "BOMBS"), (0, "GRALATS")):
        txt = str(int(me.get(key, 0) or 0)); w = int(d.textlength(txt)) if hasattr(d, "textlength") else 8 * len(txt); sp = item_sprite(typ)
        x -= w; d.text((x, 10), txt, fill=(255, 255, 255, 255)); x -= sp.width + 3; canvas.alpha_composite(sp, (x, 14 - sp.height // 2 + 4)); x -= 14
