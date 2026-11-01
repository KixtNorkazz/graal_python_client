"""Parser for .gani animation files (frames of sprite placements, one line per facing direction)."""
import re, assets

def cur_pending(block):
    return any(b for b in block[-4:])

class Gani:
    def __init__(self):
        self.sprites = {}
        self.frames = []
        self.defaults = {}
        self.single = False; self.loop = False; self.waits = []; self.setbackto = None; self.continuous = False

_cache = {}

def load(name):
    key = name.lower().removesuffix(".gani")
    if key in _cache: return _cache[key]
    p = assets.find(key + ".gani"); g = None
    if p:
        try: g = parse(open(p, encoding="latin1").read())
        except (ValueError, OSError): g = None
    _cache[key] = g; return g

def _forget_missing(key=None):
    for k in [k for k, v in _cache.items() if v is None]: del _cache[k]
assets.listeners.append(_forget_missing)

def parse(text):
    g = Gani(); lines = text.splitlines(); i = 0
    while i < len(lines):
        ln = lines[i].strip(); i += 1
        if not ln: continue
        w = ln.split()
        if w[0] == "SPRITE" and len(w) >= 7: g.sprites[int(w[1])] = (w[2], int(w[3]), int(w[4]), int(w[5]), int(w[6]))
        elif w[0].startswith("DEFAULT") and len(w) >= 2: g.defaults[w[0]] = w[1]
        elif w[0] == "SINGLEDIRECTION": g.single = True
        elif w[0] == "LOOP": g.loop = True
        elif w[0] == "CONTINUOUS": g.continuous = True
        elif w[0] == "SETBACKTO" and len(w) > 1: g.setbackto = w[1]
        elif w[0] == "ANI":
            block = []
            while i < len(lines) and lines[i].strip() != "ANIEND":
                l = lines[i].strip(); i += 1
                if l.startswith("WAIT"):
                    g.waits.append((len(g.frames) + (1 if cur_pending(block) else 0) - 1, int(l.split()[1]))); continue
                if l.startswith(("PLAYSOUND", "SETBACKTO", "STOP", "CONTINUOUS", "//")): continue
                block.append(l)
                nd = 1 if g.single else 4
                if len(block) == nd or (not l):
                    pass
            cur = []
            for l in block + [""]:
                if l: cur.append(l)
                elif cur:
                    ents = [[tuple(int(v) for v in e.split()) for e in row.split(",") if e.strip() and all(v.lstrip("-").isdigit() for v in e.split())] for row in cur]
                    if g.single: g.frames.append({d: ents[0] for d in range(4)})
                    else:
                        while len(ents) < 4: ents.append(ents[-1])
                        g.frames.append({d: ents[d] for d in range(4)})
                    cur = []
    return g


def frame_at(g, t):
    """Frame index at time t seconds (50 ms per frame, +WAIT n ticks after a frame)."""
    n = len(g.frames)
    if n <= 1: return 0
    dur = [0.05] * n
    for idx, w in g.waits:
        if 0 <= idx < n: dur[idx] += 0.05 * w
    total = sum(dur); t = t % total if g.loop or True else min(t, total)
    for i, d in enumerate(dur):
        if t < d: return i
        t -= d
    return n - 1


def duration(g):
    """Seconds one run of the animation takes (50 ms per frame plus WAIT ticks)."""
    return 0.05 * (len(g.frames) + sum(w for _, w in g.waits)) if g.frames else 0.0
