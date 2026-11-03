"""How an NPC that is a character looks in the level editor: the setcharprop lines of its script give the head, body, shield and direction."""
import re
from PIL import Image, ImageDraw
import render

_PROP = re.compile(r"setcharprop\s+#(\d+)\s*,\s*([^;\n]+?)\s*;")
_DIR = re.compile(r"\bdir\s*=\s*(\d)\s*;")
SIZE = 80
ORIGIN = 16
_cache = {}


def props_from_script(script):
    """{HEADIMAGE, BODYIMAGE, SHIELDIMAGE, SWORDIMAGE} and the direction found in a script, or None when it is not a character."""
    script = re.sub(r"//[^\n]*", "", script or "")
    if "showcharacter" not in script and "setcharprop" not in script: return None
    props, direction = {}, 2
    for num, value in _PROP.findall(script):
        if num == "3": props["HEADIMAGE"] = value
        elif num == "8": props["BODYIMAGE"] = value
        elif num == "2": props["SHIELDIMAGE"] = {"image": value}
        elif num == "1": props["SWORDIMAGE"] = {"image": value}
    m = _DIR.search(script)
    if m: direction = int(m.group(1)) & 3
    return props, direction


def missing(script):
    """The head, body and shield images a character script names that cannot be found locally."""
    found = props_from_script(script)
    if found is None: return []
    props = found[0]; names = [props.get("HEADIMAGE"), props.get("BODYIMAGE"), (props.get("SHIELDIMAGE") or {}).get("image")]
    return [n for n in names if n and render.load_image(n) is None]


def placeholder():
    """A plain figure for a character whose images are not on this computer."""
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse((ORIGIN + 6, ORIGIN - 6, ORIGIN + 26, ORIGIN + 14), fill=(235, 200, 160, 255), outline=(40, 30, 20, 255))
    d.rectangle((ORIGIN + 4, ORIGIN + 14, ORIGIN + 28, ORIGIN + 40), fill=(70, 110, 200, 255), outline=(20, 30, 60, 255))
    d.text((ORIGIN + 13, ORIGIN + 20), "?", fill=(255, 255, 255, 255))
    return im


def sprite(script):
    """An 80x80 image with the character drawn so that the NPC's tile is at (16, 16), or None when the script is not a character."""
    found = props_from_script(script)
    if found is None: return None
    props, direction = found
    key = (repr(sorted((k, repr(v)) for k, v in props.items())), direction)
    im = _cache.get(key)
    if im is None:
        im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)); render.draw_character(im, "idle", direction, props, ORIGIN, ORIGIN, 0.0)
        if render.load_image(props.get("HEADIMAGE") or "head0.png") is None and render.load_image(props.get("BODYIMAGE") or "body.png") is None: im = placeholder()
        if len(_cache) > 64: _cache.clear()
        _cache[key] = im
    return im
