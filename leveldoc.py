"""An editable .nw level: layer-0 tiles, links, signs, chests, baddies and NPCs, with undo, a tile clipboard, flood fill and saving.

The file format is GLEVNW01 as gs2emu reads and writes it: `BOARD x y width layer data` rows (two base64 characters per tile), then LINK, SIGN, CHEST,
BADDY and NPC records. Board rows of other layers are kept as they were read."""
import copy, re
from nwlevel import parse_nw

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
SIZE = 64
BADDY_NAMES = ("Gray Soldier", "Blue Soldier", "Red Soldier", "Shooting Soldier", "Swamp Soldier", "Frog", "Spider", "Golden Warrior", "Lizardon", "Dragon")
CHEST_ITEMS = ("greenrupee", "bluerupee", "redrupee", "bombs", "darts", "heart", "glove1", "bow", "bomb", "shield", "sword", "fullheart", "superbomb", "battleaxe",
               "goldensword", "mirrorshield", "glove2", "lizardshield", "lizardsword", "goldrupee", "fireball", "fireblast", "nukeshot", "joltbomb", "spinattack")
UNDO_LIMIT = 100
MAX_LAYER = 7
EMPTY = -1
_IDX = {c: i for i, c in enumerate(_B64)}


class Pattern:
    """A rectangle of tile numbers (the tile clipboard and the tiles chosen in the palette)."""
    def __init__(self, w, h, tiles): self.w, self.h, self.tiles = w, h, list(tiles)

    def at(self, x, y): return self.tiles[(y % self.h) * self.w + (x % self.w)]

    @classmethod
    def single(cls, tile): return cls(1, 1, [tile])


class LevelDoc:
    def __init__(self, name="new.nw"):
        self.name = name
        self.tiles = [0] * (SIZE * SIZE)
        self.links, self.signs, self.chests, self.baddies, self.npcs = [], [], [], [], []
        self.layers = {}
        self.backtile = 0
        self.modified = False
        self._undo, self._redo = [], []

    @classmethod
    def from_text(cls, text, name="new.nw"):
        doc = cls(name); lv = parse_nw(text, name); board = lv.layers.get(0)
        if board:
            doc.tiles = [(board[2 * i] | (board[2 * i + 1] << 8)) & 0xFFF for i in range(SIZE * SIZE)]
        doc.links, doc.signs, doc.chests = lv.links, lv.signs, lv.chests
        doc.baddies, doc.npcs = lv.baddies, lv.npcs
        for ln in text.split("\n"):
            p = ln.rstrip("\r").split()
            if len(p) >= 6 and p[0] == "BOARD" and p[4] != "0":
                try: x, y, layer = int(p[1]), int(p[2]), int(p[4])
                except ValueError: continue
                if not 0 < layer <= MAX_LAYER or not 0 <= y < SIZE: continue
                tiles = doc.layers.setdefault(layer, [EMPTY] * (SIZE * SIZE))
                for k in range(len(p[5]) // 2):
                    if 0 <= x + k < SIZE: tiles[y * SIZE + x + k] = (_IDX.get(p[5][2 * k], 0) << 6) | _IDX.get(p[5][2 * k + 1], 0)
        return doc

    @classmethod
    def load(cls, path):
        import os
        with open(path, encoding="latin1") as f: return cls.from_text(f.read(), os.path.basename(path))

    def to_text(self):
        out = ["GLEVNW01"]
        for y in range(SIZE):
            row = self.tiles[y * SIZE:(y + 1) * SIZE]
            out.append("BOARD 0 %d %d 0 %s" % (y, SIZE, "".join(_B64[(t >> 6) & 63] + _B64[t & 63] for t in row)))
        for layer in sorted(self.layers):
            tiles = self.layers[layer]
            for y in range(SIZE):
                x = 0
                while x < SIZE:
                    if tiles[y * SIZE + x] == EMPTY: x += 1; continue
                    e = x
                    while e < SIZE and tiles[y * SIZE + e] != EMPTY: e += 1
                    out.append("BOARD %d %d %d %d %s" % (x, y, e - x, layer, "".join(_B64[(t >> 6) & 63] + _B64[t & 63] for t in tiles[y * SIZE + x:y * SIZE + e])))
                    x = e
        for k in self.links: out.append("LINK %s %s %s %s %s %s %s" % (k["level"], k["x"], k["y"], k["w"], k["h"], k["nx"], k["ny"]))
        for s in self.signs: out += ["SIGN %d %d" % (s["x"], s["y"])] + s["text"].split("\n") + ["SIGNEND"]
        for c in self.chests: out.append("CHEST %d %d %s %d" % (c["x"], c["y"], c["item"], c["sign"]))
        for b in self.baddies: out += ["BADDY %s %s %d" % (_num(b["x"]), _num(b["y"]), b["type"])] + list(b["verses"]) + ["BADDYEND"]
        for n in self.npcs: out += ["NPC %s %s %s" % (n["image"] or "-", _num(n["x"]), _num(n["y"]))] + (n["script"].split("\n") if n["script"] else []) + ["NPCEND"]
        return "\n".join(out) + "\n"

    def save(self, path=None):
        import os
        path = path or self.name
        tmp = path + ".part"
        with open(tmp, "w", encoding="latin1", errors="replace", newline="\n") as f: f.write(self.to_text())
        os.replace(tmp, path); self.name = os.path.basename(path); self.modified = False

    def board(self):
        """Layer 0 as 64x64 u16 little endian, the layout the renderer takes."""
        b = bytearray(2 * SIZE * SIZE)
        for i, t in enumerate(self.tiles): b[2 * i] = t & 0xFF; b[2 * i + 1] = t >> 8
        return bytes(b)

    def _state(self): return (self.tiles[:], copy.deepcopy((self.links, self.signs, self.chests, self.baddies, self.npcs)), {k: v[:] for k, v in self.layers.items()})

    def _restore(self, st):
        self.tiles = st[0][:]; self.links, self.signs, self.chests, self.baddies, self.npcs = copy.deepcopy(st[1]); self.layers = {k: v[:] for k, v in st[2].items()}

    def begin(self):
        """Call before a change: remember the level so undo() can bring it back."""
        self._undo.append(self._state()); del self._undo[:-UNDO_LIMIT]; self._redo.clear(); self.modified = True

    def undo(self):
        if not self._undo: return False
        self._redo.append(self._state()); self._restore(self._undo.pop()); self.modified = True; return True

    def redo(self):
        if not self._redo: return False
        self._undo.append(self._state()); self._restore(self._redo.pop()); self.modified = True; return True

    @staticmethod
    def inside(x, y): return 0 <= x < SIZE and 0 <= y < SIZE

    def plane(self, layer, create=False):
        """The list of tiles of a layer (layer 0 always exists; an upper layer only once something is put on it unless create)."""
        if layer == 0: return self.tiles
        if layer not in self.layers and create: self.layers[layer] = [EMPTY] * (SIZE * SIZE)
        return self.layers.get(layer)

    def tile(self, x, y, layer=0):
        p = self.plane(layer)
        return p[y * SIZE + x] if p is not None and self.inside(x, y) else (0 if layer == 0 else EMPTY)

    def set_tile(self, x, y, t, layer=0):
        if not self.inside(x, y): return False
        p = self.plane(layer, create=t != EMPTY)
        if p is None or p[y * SIZE + x] == t: return False
        p[y * SIZE + x] = t; return True

    def paste(self, x, y, pat, layer=0):
        """Put a pattern with its top left corner at tile (x, y); what falls outside the level is cut off. Returns the number of tiles changed."""
        return sum(self.set_tile(x + i, y + j, pat.tiles[j * pat.w + i], layer) for j in range(pat.h) for i in range(pat.w))

    def copy_rect(self, x, y, w, h, layer=0):
        x0, y0 = max(0, x), max(0, y); x1, y1 = min(SIZE, x + w), min(SIZE, y + h)
        if x1 <= x0 or y1 <= y0: return None
        return Pattern(x1 - x0, y1 - y0, [self.tile(i, j, layer) for j in range(y0, y1) for i in range(x0, x1)])

    def clear_rect(self, x, y, w, h, layer=0):
        """Set a rectangle to the background tile (on an upper layer: to empty). Returns the number of tiles changed."""
        cw, ch = _clip(x, y, w, h); blank = self.backtile if layer == 0 else EMPTY
        return self.paste(max(0, x), max(0, y), Pattern(cw, ch, [blank] * (cw * ch)), layer) if cw and ch else 0

    def fill(self, x, y, pat, layer=0):
        """Flood fill from (x, y): every connected tile with the same number as the start tile gets the pattern, repeated from the start. Returns the count."""
        if not self.inside(x, y): return 0
        old = self.tile(x, y, layer); todo, seen, n = [(x, y)], set(), 0
        while todo:
            cx, cy = todo.pop()
            if (cx, cy) in seen or not self.inside(cx, cy) or self.tile(cx, cy, layer) != old: continue
            seen.add((cx, cy)); n += self.set_tile(cx, cy, pat.at(cx - x, cy - y), layer)
            todo += [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]
        return n

    KINDS = {"link": "links", "sign": "signs", "chest": "chests", "baddy": "baddies", "npc": "npcs"}

    def objects(self, kind): return getattr(self, self.KINDS[kind])

    def add_link(self, level, x, y, w, h, nx, ny):
        self.begin(); self.links.append(dict(level=level, x=int(x), y=int(y), w=max(1, int(w)), h=max(1, int(h)), nx=str(nx), ny=str(ny))); return self.links[-1]

    def add_sign(self, x, y, text=""):
        self.begin(); self.signs.append(dict(x=int(x), y=int(y), text=text.rstrip("\n"))); return self.signs[-1]

    def add_chest(self, x, y, item="greenrupee", sign=0):
        self.begin(); self.chests.append(dict(x=int(x), y=int(y), item=item, sign=int(sign))); return self.chests[-1]

    def add_baddy(self, x, y, type=0):
        self.begin(); self.baddies.append(dict(x=float(x), y=float(y), type=int(type), verses=["", "", ""])); return self.baddies[-1]

    def add_npc(self, x, y, image="-", script=""):
        self.begin(); self.npcs.append(dict(image=image, x=float(x), y=float(y), script=script)); return self.npcs[-1]

    def remove(self, kind, index):
        self.begin(); del self.objects(kind)[index]

    def edit(self, kind, index, **fields):
        """Change fields of one object (remembered for undo)."""
        self.begin(); self.objects(kind)[index].update(fields)

    def move(self, kind, index, dx, dy, record=True):
        """Shift an object by whole tiles; record=False continues a drag that has already been remembered for undo."""
        if record: self.begin()
        o = self.objects(kind)[index]
        o["x"] = _shift(o["x"], dx); o["y"] = _shift(o["y"], dy)

    def objects_in(self, x, y, w, h):
        """Objects inside a rectangle of tiles: [(kind, index)]. An object counts by its top left tile; a link only when it lies completely inside."""
        hits = []
        for kind in ("chest", "sign", "baddy", "npc"):
            for i, o in enumerate(self.objects(kind)):
                if x <= int(o["x"]) < x + w and y <= int(o["y"]) < y + h: hits.append((kind, i))
        for i, k in enumerate(self.links):
            if x <= k["x"] and k["x"] + k["w"] <= x + w and y <= k["y"] and k["y"] + k["h"] <= y + h: hits.append(("link", i))
        return hits

    def copy_objects(self, x, y, w, h):
        """Copies of the objects inside a rectangle, with positions relative to its top left corner: [(kind, object)]."""
        out = []
        for kind, i in self.objects_in(x, y, w, h):
            o = copy.deepcopy(self.objects(kind)[i]); o["x"] = _shift(o["x"], -x); o["y"] = _shift(o["y"], -y); out.append((kind, o))
        return out

    def add_objects(self, items, x, y):
        """Put copies of (kind, object) pairs from copy_objects() with the rectangle's corner at tile (x, y); objects that would leave the level are skipped.
        Call begin() first. Returns the number added."""
        n = 0
        for kind, o in items:
            o = copy.deepcopy(o); o["x"] = _shift(o["x"], x); o["y"] = _shift(o["y"], y)
            w, h = (o["w"], o["h"]) if kind == "link" else (1, 1)
            if 0 <= o["x"] and 0 <= o["y"] and o["x"] + w <= SIZE and o["y"] + h <= SIZE: self.objects(kind).append(o); n += 1
        return n

    def remove_objects(self, hits):
        """Delete several objects at once (call begin() first)."""
        for kind, i in sorted(hits, key=lambda h: -h[1]): del self.objects(kind)[i]

    def shift_objects(self, hits, dx, dy):
        """Move several objects by whole tiles (call begin() first)."""
        for kind, i in hits:
            o = self.objects(kind)[i]; o["x"] = _shift(o["x"], dx); o["y"] = _shift(o["y"], dy)

    def objects_at(self, x, y):
        """Objects covering tile (x, y), topmost first: [(kind, index)]."""
        hits = []
        for i, c in enumerate(self.chests):
            if c["x"] == x and c["y"] == y: hits.append(("chest", i))
        for i, s in enumerate(self.signs):
            if s["x"] == x and s["y"] == y: hits.append(("sign", i))
        for i, b in enumerate(self.baddies):
            if int(b["x"]) == x and int(b["y"]) == y: hits.append(("baddy", i))
        for i, n in enumerate(self.npcs):
            if int(n["x"]) <= x <= int(n["x"]) + 1 and int(n["y"]) <= y <= int(n["y"]) + 1: hits.append(("npc", i))
        for i, k in enumerate(self.links):
            if k["x"] <= x < k["x"] + k["w"] and k["y"] <= y < k["y"] + k["h"]: hits.append(("link", i))
        return hits


def _num(v):
    """A coordinate as text: 12 for 12.0, otherwise the shortest text that reads back as the same number."""
    t = repr(v)
    return t[:-2] if t.endswith(".0") else t

def _shift(v, d): return v + d if isinstance(v, int) else float(v) + d

def _clip(x, y, w, h):
    x0, y0 = max(0, x), max(0, y); return (max(0, min(SIZE, x + w) - x0), max(0, min(SIZE, y + h) - y0))
