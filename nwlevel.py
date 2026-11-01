"""GLEVNW01 (.nw) level reader: BOARD rows (2 base64 chars per tile), LINK, NPC blocks, SIGN."""
import re

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_IDX = {c: i for i, c in enumerate(_B64)}

class NwLevel:
    def __init__(self, name):
        self.name, self.layers, self.links, self.npcs, self.signs, self.chests = name, {}, [], [], [], []

    @property
    def board(self):
        """Layer 0 as 64x64 u16 LE (same layout the server sends in PLO_BOARDPACKET)."""
        return bytes(self.layers.get(0) or bytearray(8192))

def parse_nw(text, name="level.nw"):
    lv = NwLevel(name); lines = text.replace("\r", "").split("\n")
    if not lines or not lines[0].startswith("GLEVNW01"): return lv
    i = 1
    while i < len(lines):
        ln = lines[i]; i += 1; p = ln.split()
        if not p: continue
        if p[0] == "BOARD" and len(p) >= 6:
            try: x, y, w, layer, data = int(p[1]), int(p[2]), int(p[3]), int(p[4]), p[5]
            except ValueError: continue
            b = lv.layers.setdefault(layer, bytearray(8192))
            for k in range(min(w, len(data) // 2)):
                tx = x + k
                if tx >= 64 or y >= 64: break
                t = (_IDX.get(data[2 * k], 0) << 6) | _IDX.get(data[2 * k + 1], 0)
                o = 2 * (y * 64 + tx); b[o] = t & 0xFF; b[o + 1] = t >> 8
        elif p[0] == "LINK" and len(p) >= 8:
            try: lv.links.append(dict(level=" ".join(p[1:-6]), x=int(p[-6]), y=int(p[-5]), w=int(p[-4]), h=int(p[-3]), nx=p[-2], ny=p[-1]))
            except ValueError: pass
        elif p[0] == "NPC" and len(p) >= 4:
            body = []
            while i < len(lines) and lines[i].strip() != "NPCEND": body.append(lines[i]); i += 1
            i += 1
            try: lv.npcs.append(dict(image=" ".join(p[1:-2]), x=float(p[-2]), y=float(p[-1]), script="\n".join(body)))
            except ValueError: pass
        elif p[0] == "CHEST" and len(p) >= 4:
            try: lv.chests.append(dict(x=int(p[1]), y=int(p[2]), item=p[3], sign=int(p[4]) if len(p) > 4 else 0))
            except ValueError: pass
        elif p[0] == "SIGN" and len(p) >= 3:
            body = []
            while i < len(lines) and lines[i].strip() != "SIGNEND": body.append(lines[i]); i += 1
            i += 1
            lv.signs.append(dict(x=int(p[1]), y=int(p[2]), text="\n".join(body)))
    return lv

def load_nw(path):
    with open(path, encoding="latin1") as f: return parse_nw(f.read(), path.rsplit("/", 1)[-1])
